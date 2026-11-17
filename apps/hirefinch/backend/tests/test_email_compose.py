"""Recruiter emails in the user's style, and web search through a licensed API."""

from __future__ import annotations

import httpx
import pytest
from agents_core.llm.testing import ScriptedLLM

from hirefinch.domain import EmailStyle
from hirefinch.errors import ServiceError
from hirefinch.net import SafeFetcher
from hirefinch.services.email_compose import EmailFacts, compose, from_template, render_html
from hirefinch.services.websearch import search_jobs

FACTS = EmailFacts(name="Riya Sharma", job_title="Backend Engineer", company="Acme", job_url="https://jobs.acme.io/1",
                   first_name="Sam", current_title="Software Engineer", current_company="Initech", years="4",
                   skills=["Java", "Kafka"], projects=["Payments platform"], tailored=True,
                   contact_lines=["riya@example.com", "+91 90000 00000"])


def test_user_template_and_signature():
    style = EmailStyle(template="Dear {first_name},\n\nRe: {job_title} ({company}).\n{qualifications}\n\n{signature}",
                       subject_template="Application: {job_title}, {name}", signature="Riya\nriya.dev")
    mail = from_template(FACTS, style)
    assert mail.subject == "Application: Backend Engineer, Riya Sharma"
    assert mail.body.startswith("Dear Sam,") and mail.body.endswith("Riya\nriya.dev") and "I am currently working as a Software Engineer at Initech" in mail.body


@pytest.mark.parametrize("bad", ["Hi {nickname}", "Hi {", "{0}"])
def test_unknown_placeholders_are_rejected(bad):
    with pytest.raises(ValueError):
        EmailStyle(template=bad)


async def test_ai_draft_used_when_it_keeps_to_the_facts():
    llm = ScriptedLLM([{"subject": "Backend Engineer role at Acme", "body": "Hi Sam,\n\nI'd love to be considered for the Backend "
                        "Engineer role at Acme. I work with Java and Kafka at Initech.\n\nMy resume is attached."}])
    mail = await compose(FACTS, EmailStyle(tone="warm"), llm, allow_ai=True)
    assert mail.written_by == "ai" and mail.body.endswith("riya@example.com\n+91 90000 00000")
    assert "friendly" in llm.calls[0][0][1].content  # the tone reached the model


@pytest.mark.parametrize("body", [
    "Hi Sam, I led a team of 25 on the Backend Engineer role at Acme stack.",  # a number not in the facts
    "Hi Sam, for the Backend Engineer role at Acme I bring deep Rust and Golang expertise.",  # unverified skills
    "Hi Sam, as discussed on our call, the Backend Engineer role at Acme suits me.",  # invented conversation
    "Hi Sam, see https://evil.example for my Backend Engineer application at Acme.",  # a new link
    "Hi Sam, I would like to apply. My resume is attached and I look forward to hearing.",  # no title/company
])
async def test_ai_draft_falls_back_when_it_adds_facts(body):
    mail = await compose(FACTS, EmailStyle(), ScriptedLLM([{"subject": "My application", "body": body}]), allow_ai=True)
    assert mail.written_by == "template"


def test_default_email_is_natural_with_standard_signature():
    facts = EmailFacts(name="Priya Sharma", job_title="Backend Engineer", company="Acme", job_url="https://jobs.acme.io/1",
                       current_title="Software Engineer", current_company="Globex", years="4", skills=["Java", "Spring Boot"],
                       tailored=True, email="priya@example.com", phone="+91 98765 43210", linkedin="https://linkedin.com/in/priyasharma")
    mail = from_template(facts, EmailStyle())
    assert mail.subject == "Application for Backend Engineer – Priya Sharma"
    assert mail.body.startswith("Dear Hiring Team at Acme,") and "tailored" not in mail.body.lower()
    assert "I have attached my resume for your review." in mail.body
    assert mail.body.endswith("Best regards,\n**Priya Sharma**\nSoftware Engineer\n\n📧 priya@example.com\n📞 +91 98765 43210\n"
                              "🔗 https://linkedin.com/in/priyasharma")
    html = render_html(mail.body)
    assert "<strong>Priya Sharma</strong>" in html and "**" not in html
    from hirefinch.services.email_compose import plain_text

    assert "**" not in plain_text(mail.body)


async def test_ai_draft_that_mentions_tailoring_is_rejected():
    llm = ScriptedLLM([{"subject": "Backend Engineer at Acme", "body": "Dear Sam,\n\nI'd like to apply for the Backend Engineer "
                        "role at Acme. I've attached a resume tailored to this role.\n\nBest regards,"}])
    assert (await compose(FACTS, EmailStyle(), llm, allow_ai=True)).written_by == "template"


def test_ats_file_name_and_contact_formats():
    from hirefinch.text import format_phone, full_url, resume_filename

    assert resume_filename("PRIYA ANIL SHARMA") == "Priya_Anil_Sharma_Resume.pdf"
    assert resume_filename("Priya Sharma", ".docx") == "Priya_Sharma_Resume.docx"
    assert format_phone("9876543210") == "+91 98765 43210" and full_url("linkedin.com/in/x") == "https://linkedin.com/in/x"


def test_html_version_escapes_everything():
    out = render_html("Hi <b>Sam</b>,\n\n- Java & Kafka\n- <script>x</script>\n\nhttps://jobs.acme.io/1?a=1")
    assert "<script>" not in out and "&lt;script&gt;" in out and "<li>Java &amp; Kafka</li>" in out
    assert '<a href="https://jobs.acme.io/1?a=1">' in out


async def public(host):
    return ["93.184.216.34"]


async def test_brave_search_marks_what_can_be_read():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-subscription-token")
        seen["q"] = request.url.params["q"]
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Backend Engineer - Acme", "url": "https://jobs.lever.co/acme/1", "description": "Java"},
            {"title": "Backend Engineer | LinkedIn", "url": "https://www.linkedin.com/jobs/view/2", "description": ""},
            {"title": "Plain http", "url": "http://insecure.example/job", "description": ""}]}})

    f = SafeFetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), allowed_hosts=frozenset(), user_agent="t",
                    min_interval=0, resolver=public, max_retries=0)
    hits = await search_jobs(f, {"provider": "brave", "api_key": "k-123"}, "backend engineer", "Pune")
    assert seen["key"] == "k-123" and "site:jobs.lever.co" in seen["q"] and "Pune" in seen["q"]
    assert [(h.fetchable, h.ats) for h in hits] == [(True, True), (False, False)]  # http result dropped
    with pytest.raises(ServiceError, match="not set up"):
        await search_jobs(f, None, "backend")
