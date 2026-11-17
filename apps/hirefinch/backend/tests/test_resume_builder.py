"""Resume Builder: health check, save as the resume in use, and AI help that cannot invent facts."""

from __future__ import annotations

from agents_core.llm.testing import ScriptedLLM

from hirefinch.domain import ResumeDocument
from hirefinch.resume.coaching import review
from hirefinch.resume.validator import rewrite_problem

DOC = {
    "contact": {"name": "Riya Sharma", "email": "riya.sharma@example.com", "phone": "+91 90000 00000",
                "links": ["https://linkedin.com/in/riya"]},
    "summary": "Backend engineer with 4 years of Java and Spring Boot experience building payment services.",
    "skills": [{"name": "Backend", "items": ["Java", "Spring Boot", "Kafka", "MySQL", "Docker", "AWS"]}],
    "experience": [{
        "id": "", "title": "Software Engineer", "company": "Example Bank", "start": "2021-06-01", "is_current": True,
        "bullets": [{"id": "", "text": "Built a Kafka-based payment events pipeline handling 2M events a day"},
                    {"id": "", "text": "Reduced checkout API latency 35% by adding Redis caching"}],
    }],
    "education": ["B.E. Computer Engineering, Pune University, 2021"],
}


def test_review_flags_duty_language_and_missing_results():
    doc = ResumeDocument.model_validate({**DOC, "experience": [{
        "id": "e1", "title": "Developer", "company": "Acme", "date_text": "2020 – 2022",
        "bullets": [{"id": "b1", "text": "Responsible for the login page"}, {"id": "b2", "text": "Worked on APIs with my team"}],
    }]})
    report = review(doc)
    messages = " ".join(t.message for t in report.tips)
    assert "describes a duty" in messages and "Leave out" in messages and "show a result in numbers" in messages
    assert report.score < review(ResumeDocument.model_validate(DOC)).score


async def test_save_makes_it_the_resume_in_use(client):
    review_r = await client.post("/api/resume-builder/review", json=DOC)
    assert review_r.status_code == 200 and review_r.json()["score"] >= 80
    pdf = await client.post("/api/resume-builder/preview", json=DOC)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    saved = await client.post("/api/resume-builder/save", json=DOC)
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["is_active"] and body["filename"] == "Riya_Sharma_Resume.pdf"
    entry = body["document"]["experience"][0]
    assert entry["date_text"] == "Jun 2021 – Present" and all(b["id"] for b in entry["bullets"])
    masters = (await client.get("/api/resumes/masters")).json()
    assert [m["id"] for m in masters if m["is_active"]] == [body["id"]]


async def test_save_needs_a_name_and_some_experience(client):
    r = await client.post("/api/resume-builder/save", json={"contact": {"name": "Riya"}})
    assert r.status_code == 422 and "at least your name" in r.json()["message"]


def test_drafts_may_grow_but_never_gain_numbers():
    draft = "made login api"
    assert rewrite_problem(draft, "Built the login API for the customer sign-in flow", draft=True) is None
    assert rewrite_problem(draft, "Built the login API using Spring Boot", draft=True) == "adds technologies: Spring Boot"
    assert rewrite_problem(draft, "Built the login API serving 10,000 users", draft=True) == "numbers added or dropped"
    # The person's own figure may be used.
    assert rewrite_problem(draft, "Built the login API serving 10,000 users", "about 10,000 users", draft=True) is None


async def test_ai_help_rejects_invented_numbers_and_asks_instead(client, runtime):
    runtime.llm_override = ScriptedLLM([
        {"text": "Built the login API, cutting sign-in time 60%", "question": "How much faster did sign-in get?"},
        {"text": "Built the login API, cutting sign-in time 40%", "question": ""},
    ])
    try:
        invented = await client.post("/api/resume-builder/improve-bullet", json={"text": "made login api", "role": "Developer"})
        given = await client.post("/api/resume-builder/improve-bullet",
                                  json={"text": "made login api", "role": "Developer", "facts": "sign-in got 40% faster"})
    finally:
        runtime.llm_override = None
    assert invented.json()["text"] == "" and "numbers" in invented.json()["rejected"]
    assert invented.json()["question"] == "How much faster did sign-in get?"
    assert given.json() == {"text": "Built the login API, cutting sign-in time 40%", "question": "", "rejected": ""}


async def test_summary_must_come_from_the_resume(client, runtime):
    runtime.llm_override = ScriptedLLM([{"summary": "Backend engineer who led a team of 12 building Kubernetes platforms."}])
    try:
        r = await client.post("/api/resume-builder/summary", json=DOC)
    finally:
        runtime.llm_override = None
    assert r.status_code == 502 and "not on your resume" in r.json()["message"]


async def test_ai_help_needs_an_ai_connection(client):
    r = await client.post("/api/resume-builder/improve-bullet", json={"text": "made login api"})
    assert r.status_code == 409 and "Integrations" in r.json()["message"]


async def test_review_still_answers_when_a_draft_is_over_the_limits(client):
    r = await client.post("/api/resume-builder/review", json={**DOC, "summary": "word " * 300})
    assert r.status_code == 200
    tips = [t for t in r.json()["tips"] if t["section"] == "summary"]
    assert len(tips) == 1 and tips[0]["level"] == "fix" and "Shorten the summary" in tips[0]["message"]


def test_one_habit_repeated_is_scored_as_one_problem():
    from hirefinch.resume.coaching import Tip, score

    once = [Tip("fix", "bullets", "Leave out I", "b1", "first_person")]
    four = [Tip("fix", "bullets", "Leave out I", f"b{i}", "first_person") for i in range(4)]
    assert score(once) == 88 and score(four) == 79  # 12, then 3 for each repeat
    assert score([Tip("fix", "bullets", "x", f"b{i}", "first_person") for i in range(20)]) == 79  # capped at 21
    assert score([Tip("fix", "contact", "Add your full name."), Tip("fix", "contact", "Add an email address.")]) == 76
