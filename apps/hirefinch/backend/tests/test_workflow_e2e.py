"""The full supervised workflow through the HTTP API, with mock sources, a mock ATS and a capturing
email sender. Mirrors the Definition of Done, including a restart that must not duplicate anything.
"""

from __future__ import annotations

import hashlib

import httpx

from hirefinch.app import create_app
from hirefinch.runtime import build_runtime


async def _setup(client: httpx.AsyncClient, resume_docx: bytes) -> None:
    upload = await client.post("/api/resumes/masters", files={"file": ("cv.docx", resume_docx)})
    assert upload.status_code == 201, upload.text
    assert upload.json()["is_active"]
    profile = (await client.get("/api/profile")).json()
    assert profile["candidate"]["years_experience"] > 3
    body = profile["profile"] | {"notification_email": "me@example.com", "notice_period_days": 30}
    assert (await client.put("/api/profile", json=body)).status_code == 200


async def _job_id(client: httpx.AsyncClient, external_title: str, company: str) -> int:
    jobs = (await client.get("/api/jobs", params={"include_duplicates": "true", "page_size": 100})).json()["items"]
    return next(j["id"] for j in jobs if j["title"] == external_title and j["company"] == company)


async def test_definition_of_done(client, resume_docx, sender, settings, sessionmaker):
    await _setup(client, resume_docx)

    # 3. retrieve jobs from a connector and advance the pipeline (supervised mode by default)
    run = (await client.post("/api/automation/run", params={"source": "mock"})).json()
    assert run["new_jobs"] >= 6, run
    jobs = (await client.get("/api/jobs")).json()["items"]
    by_title = {(j["title"], j["company"]): j for j in jobs}
    assert ("AI Agent Engineer", "Acme Agents Pvt Ltd") not in by_title  # cross-post hidden as a duplicate

    # 4. score explained, disqualifiers respected, unsafe postings held back
    java = by_title[("Backend Engineer (Java)", "FinStack Technologies Pvt. Ltd.")]
    detail = (await client.get(f"/api/jobs/{java['id']}")).json()
    assert detail["match"]["band"] in ("high", "good") and detail["match"]["explanation"]["why_matches"]
    assert by_title[("Principal Software Engineer", "BigCo")]["band"] == "disqualified"
    assert by_title[("Software Engineer", "SmallShop")]["band"] == "disqualified"
    tricky = by_title[("Full Stack Engineer", "TrickyCo")]
    assert tricky["flags"]["prompt_injection"]
    scam = by_title[("Java Developer", "QuickHire")]
    assert scam["flags"]["suspicious"]
    # Flagged postings stop for your review: no resume is generated and nothing is queued.
    assert tricky["status"] == "match_evaluated" and scam["status"] == "match_evaluated"

    # 5–6. tailored DOCX and PDF generated and validated
    assert detail["status"] in ("awaiting_approval",), detail["status"]
    version = detail["resume_versions"][0]
    assert version["valid"]
    full = (await client.get(f"/api/resumes/versions/{version['id']}")).json()
    assert full["report"]["changes"] and full["text"] and full["master_text"]
    pdf = await client.get(f"/api/resumes/versions/{version['id']}/download", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert hashlib.sha256(pdf.content).hexdigest() == version["pdf_sha256"]
    docx = await client.get(f"/api/resumes/versions/{version['id']}/download", params={"format": "docx"})
    assert docx.status_code == 200 and docx.content[:2] == b"PK"

    # 7–8. queued; supervised policy requires approval; unknown question must be answered first
    queue = (await client.get("/api/applications/queue")).json()
    app = next(a for a in queue["applications"] if a["job_id"] == java["id"])
    assert any("supervised" in r for r in app["auto_blockers"])
    java_q = next(a for a in app["answers"] if "Java" in a["question"])
    assert java_q["needs_user"] and java_q["answer"] is None
    blocked = await client.post(f"/api/applications/{app['id']}/approve", json={})
    assert blocked.status_code == 409 and "answer the question" in blocked.json()["message"]
    await client.put(f"/api/applications/{app['id']}/answers", json={"answer_id": java_q["id"], "answer": "4"})

    # 9. approve → mocked submission with confirmation
    approved = (await client.post(f"/api/applications/{app['id']}/approve", json={})).json()
    assert approved["job_status"] == "applied" and approved["outcome"] == "confirmed"
    assert approved["confirmation_ref"].startswith("MOCK-")
    assert approved["submitted_file_sha256"] == version["pdf_sha256"]

    # 10–11. recruiter draft for the AI role (applied by email is blocked: the local mailbox is not real)
    ai = by_title[("AI Agent Engineer", "Acme Agents")]
    ai_detail = (await client.get(f"/api/jobs/{ai['id']}")).json()
    recruiter = next(c for c in ai_detail["recruiters"] if c["email"].startswith("priya"))
    assert recruiter["verified"]
    draft = (await client.post(f"/api/outreach/contacts/{recruiter['id']}/draft")).json()
    assert "Priya" in draft["body"] and "AI Agent Engineer" in draft["subject"]
    again = (await client.post(f"/api/outreach/contacts/{recruiter['id']}/draft")).json()
    assert again["id"] == draft["id"]  # one draft per recipient per job
    sent = (await client.post(f"/api/outreach/drafts/{draft['id']}/send")).json()
    assert sent["status"] == "sent"
    mail, message = sender.sent[-1]
    assert mail.to == "priya.raman@acme-agents.example.com"
    attachment = next(message.iter_attachments())
    ai_version = ai_detail["resume_versions"][0]
    assert hashlib.sha256(attachment.get_content()).hexdigest() == ai_version["pdf_sha256"]
    assert (await client.post(f"/api/outreach/drafts/{draft['id']}/send")).status_code == 409

    # Notifications carry the exact submitted resume.
    await client.post("/api/notifications/process")
    applied_mail = next(m for m, _ in sender.sent if m.subject.startswith("Applied: Backend Engineer (Java)"))
    assert applied_mail.to == "me@example.com"
    assert applied_mail.attachments[0].sha256 == version["pdf_sha256"]

    # 12. tracker shows the result
    tracker = (await client.get("/api/applications")).json()
    record = next(a for a in tracker if a["job_id"] == java["id"])
    assert record["outcome"] == "confirmed" and record["attempts"][0]["status"] == "succeeded"
    csv = await client.get("/api/applications/export.csv")
    assert "Backend Engineer (Java)" in csv.text

    # 13. restart: a fresh app on the same database repeats discovery and the pipeline; nothing duplicates
    emails_before = len(sender.sent)
    async with httpx.AsyncClient() as http:
        rt2 = build_runtime(settings, sessionmaker=sessionmaker, sender=sender, http=http)
        app2 = create_app(settings, runtime=rt2)
        async with app2.router.lifespan_context(app2):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://test") as c2:
                c2.headers["x-csrf-token"] = (await c2.get("/api/auth/csrf")).json()["csrf_token"]
                signin = await c2.post("/api/auth/login", json={"email": "riya.sharma@example.com",
                                                                "password": "correct-horse-battery-staple"})
                assert signin.status_code == 200  # sessions are stored server-side, so they survive restarts too
                rerun = (await c2.post("/api/automation/run", params={"source": "mock"})).json()
                assert rerun["new_jobs"] == 0
                await c2.post("/api/notifications/process")
                again = next(a for a in (await c2.get("/api/applications")).json() if a["job_id"] == java["id"])
                assert len(again["attempts"]) == 1
                drafts = (await c2.get("/api/outreach")).json()["drafts"]
                assert len([d for d in drafts if d["to"].startswith("priya")]) == 1
    assert len(sender.sent) == emails_before

    # 14. audit trail recorded the important actions
    audit = (await client.get("/api/audit", params={"action": "application"})).json()
    actions = {e["action"] for e in audit["items"]}
    assert {"application.prepared", "application.approved", "application.submitted"} <= actions


async def test_manual_import_and_manual_application(client, resume_docx):
    await _setup(client, resume_docx)
    created = await client.post("/api/jobs/import", json={
        "title": "Java Developer", "company": "Example Bank", "url": "https://careers.example-bank.example/jobs/42",
        "location": "Mumbai", "work_mode": "hybrid",
        "description": "Requirements\n- 3+ years of experience\n- Java, Spring Boot, Microservices, Kafka, MySQL\nSalary 30-40 LPA",
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    detail = (await client.get(f"/api/jobs/{job_id}")).json()
    assert detail["source"] == "manual" and detail["apply_method"] == "manual" and detail["match"]
    await client.post(f"/api/jobs/{job_id}/tailor")
    app = (await client.post(f"/api/jobs/{job_id}/application")).json()
    assert any("employer's site" in r for r in app["pause_reasons"])
    done = (await client.post(f"/api/applications/{app['id']}/confirm-manual", json={"reference": "EB-123"})).json()
    assert done["job_status"] == "applied" and done["outcome"] == "confirmed"
    no_ref_job = (await client.post("/api/jobs/import", json={
        "title": "Backend Engineer", "company": "Example Pay", "url": "https://jobs.example-pay.example/7",
        "description": "Requirements\n- 3+ years of experience\n- Java, Spring Boot, Kafka, PostgreSQL",
    })).json()["id"]
    await client.post(f"/api/jobs/{no_ref_job}/tailor")
    app2 = (await client.post(f"/api/jobs/{no_ref_job}/application")).json()
    uncertain = (await client.post(f"/api/applications/{app2['id']}/confirm-manual", json={})).json()
    assert uncertain["outcome"] == "uncertain"  # your word without a reference is not a confirmation
