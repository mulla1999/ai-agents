"""Fixtures: in-memory SQLite, a fictional resume, a capturing email sender, no network, no real LLM."""

from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from hirefinch.app import create_app
from hirefinch.config import Settings
from hirefinch.db import Base, create_sessionmaker
from hirefinch.domain import (
    Bullet,
    Contact,
    ExperienceEntry,
    ProjectEntry,
    ResumeDocument,
    SkillGroup,
)
from hirefinch.notifications.email import EmailSender, OutgoingEmail
from hirefinch.resume.render import render_docx, render_pdf
from hirefinch.runtime import build_runtime


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "disabled-in-tests")  # a developer's .env must not reach a real model


def fictional_resume() -> ResumeDocument:
    """A made-up person. Tests never use a real resume."""
    return ResumeDocument(
        contact=Contact(name="RIYA SHARMA", headline="Software Engineer · Java · Spring Boot · AI Agents",
                        email="riya.sharma@example.com", phone="+91 90000 00000", location="Pune, Maharashtra",
                        links=["linkedin.com/in/riya-example"]),
        summary=("Software Engineer with 4 years of experience building Java and Spring Boot microservices. "
                 "Builds AI agents with Google ADK and RAG pipelines on GCP. "
                 "Ships React and TypeScript frontends. Leads a 3-member team."),
        skills=[
            SkillGroup(name="Languages", items=["Java 17", "Python 3.12", "TypeScript", "SQL"]),
            SkillGroup(name="Backend", items=["Spring Boot", "Hibernate", "REST APIs", "Microservices", "Kafka"]),
            SkillGroup(name="Frontend", items=["React.js", "HTML5", "CSS3"]),
            SkillGroup(name="AI", items=["Google ADK", "Vertex AI", "RAG", "Vector Search", "LLM Orchestration", "MCP"]),
            SkillGroup(name="Cloud & DevOps", items=["AWS", "GCP", "Docker", "Kubernetes", "GitLab CI/CD"]),
            SkillGroup(name="Data & Testing", items=["MySQL", "PostgreSQL", "Redis", "JUnit 5", "Mockito"]),
        ],
        experience=[
            ExperienceEntry(id="e1", title="Software Engineer", company="Example Automation Pvt. Ltd.",
                            location="Pune, India", start=date(2024, 3, 1), is_current=True,
                            date_text="March 2024 – Present", bullets=[
                                Bullet(id="e1b1", text="Built Java 17 Spring Boot microservices with Kafka event-driven pipelines."),
                                Bullet(id="e1b2", text="Built AI agents with Google ADK on Vertex AI with RAG and vector search over contracts."),
                                Bullet(id="e1b3", text="Engineered a multi-LLM orchestration layer with JSON-schema validation."),
                                Bullet(id="e1b4", text="Built React and TypeScript dashboards with WebSockets."),
                            ]),
            ExperienceEntry(id="e2", title="Associate Software Engineer", company="Example Services Ltd.",
                            location="Pune, India", start=date(2022, 9, 1), end=date(2024, 2, 1),
                            date_text="September 2022 – February 2024", bullets=[
                                Bullet(id="e2b1", text="Developed 20+ REST APIs with Hibernate and MySQL."),
                                Bullet(id="e2b2", text="Wrote JUnit 5 and Mockito tests for core services."),
                                Bullet(id="e2b3", text="Automated PDF report generation."),
                            ]),
            ExperienceEntry(id="e3", title="Software Engineer Intern", company="Example Services Ltd.",
                            location="Pune, India", start=date(2022, 6, 1), end=date(2022, 8, 1),
                            date_text="June 2022 – August 2022", is_internship=True, bullets=[
                                Bullet(id="e3b1", text="Built Spring Boot REST endpoints."),
                            ]),
        ],
        projects=[
            ProjectEntry(id="p1", name="ContractBot — AI contract analysis", subtitle="Company product",
                         technologies=["Python", "Google ADK", "Vertex AI", "RAG"],
                         bullets=[Bullet(id="p1b1", text="RAG agent on Vertex AI for contract analysis.")]),
            ProjectEntry(id="p2", name="School Portal", subtitle="Client project",
                         technologies=["Java", "Spring Boot", "MySQL", "React"],
                         bullets=[Bullet(id="p2b1", text="Student management platform with REST APIs.")]),
        ],
        education=["Bachelor of Technology (B.Tech), Computer Science — Example University, 2022"],
    )


@pytest.fixture
def resume_doc() -> ResumeDocument:
    return fictional_resume()


@pytest.fixture
def resume_docx(tmp_path: Path, resume_doc: ResumeDocument) -> bytes:
    path = tmp_path / "fictional.docx"
    render_docx(resume_doc, path)
    return path.read_bytes()


@pytest.fixture
def resume_pdf(tmp_path: Path, resume_doc: ResumeDocument) -> bytes:
    path = tmp_path / "fictional.pdf"
    render_pdf(resume_doc, path)
    return path.read_bytes()


class CapturingSender(EmailSender):
    """Pretends to deliver (so email routes are usable) and records every message. Sends nothing."""

    name = "capture"
    delivers = True

    def __init__(self) -> None:
        super().__init__("agent@example.com")
        self.sent: list[tuple[OutgoingEmail, EmailMessage]] = []
        self.fail_next: list[Exception] = []

    async def _send(self, msg: EmailMessage, mail: OutgoingEmail) -> str:
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.sent.append((mail, msg))
        return "captured in test"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, environment="test", scheduler_enabled=False, data_dir=tmp_path / "data",
                    artifacts_dir=tmp_path / "artifacts", http_min_interval_seconds=0)


@pytest.fixture
async def sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(dbapi_connection, _record):  # as in production: cascades and RESTRICT enforced
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
def sender() -> CapturingSender:
    return CapturingSender()


@pytest.fixture
async def runtime(settings, sessionmaker, sender):
    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call to {request.url}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(no_network))
    rt = build_runtime(settings, sessionmaker=sessionmaker, sender=sender, http=http)
    yield rt
    await rt.close()


PASSWORD = "correct-horse-battery-staple"


async def make_user(sessionmaker, email: str, role: str = "user", status: str = "active") -> int:
    """A verified account, created directly (registration itself is tested in test_accounts)."""
    from hirefinch.db import AppUser, utcnow
    from hirefinch.security.passwords import hash_password

    async with sessionmaker() as db:
        user = AppUser(email=email, password_hash=hash_password(PASSWORD), role=role, status=status,
                       email_verified_at=utcnow(), consent_at=utcnow())
        db.add(user)
        await db.commit()
        return user.id


@pytest.fixture
async def user_id(sessionmaker) -> int:
    return await make_user(sessionmaker, "riya.sharma@example.com", role="superadmin")


@pytest.fixture
async def urt(runtime, sessionmaker, user_id):
    """The signed-in user's runtime, for service-level tests."""
    async with sessionmaker() as db:
        return await runtime.for_user(db, user_id)


@pytest.fixture
def app(settings, runtime):
    return create_app(settings, runtime=runtime)


async def signed_in(app, email: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    response = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
async def client(app, user_id):
    async with app.router.lifespan_context(app):
        c = await signed_in(app, "riya.sharma@example.com")
        yield c
        await c.aclose()
