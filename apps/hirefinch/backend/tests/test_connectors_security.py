"""Connectors against recorded API shapes, the safe fetcher (SSRF, allowlist, robots), connector
failures, and API security (CSRF, sign-in, configuration validation, mode confirmation)."""

from __future__ import annotations

import json
import os

import httpx
import pytest
from sqlalchemy import select

from hirefinch.config import Settings
from hirefinch.connectors.ats import AshbyConnector, GreenhouseConnector, LeverConnector
from hirefinch.connectors.base import ConnectorAuthError, SourceContext
from hirefinch.connectors.web import AdzunaConnector, CareerPageConnector, job_postings_from_html
from hirefinch.db import JobSource
from hirefinch.domain import Preferences
from hirefinch.net import BlockedURL, SafeFetcher
from hirefinch.services.jobs import ensure_sources
from hirefinch.workflow.pipeline import run_discovery


async def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def fetcher(handler, hosts: set[str]) -> SafeFetcher:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SafeFetcher(client, allowed_hosts=frozenset(hosts), user_agent="test", min_interval=0, resolver=public_resolver,
                       max_retries=1)


def ctx(settings, f, config) -> SourceContext:
    return SourceContext(settings=settings, fetcher=f, preferences=Preferences(), config=config)


async def test_greenhouse(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/acme/jobs" and request.url.params["content"] == "true"
        return httpx.Response(200, json={"jobs": [{"id": 11, "title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/11",
                                                   "location": {"name": "Remote - India"}, "content": "&lt;p&gt;Java and Kafka&lt;/p&gt;",
                                                   "updated_at": "2026-10-20T10:00:00Z", "company_name": "Acme"}]})

    result = await GreenhouseConnector().fetch(ctx(settings, fetcher(handler, {"boards-api.greenhouse.io"}),
                                                   {"boards": [{"token": "acme", "company": "Acme"}]}))
    job = result.jobs[0]
    assert (job.external_id, job.company, job.work_mode) == ("11", "Acme", "remote")
    assert "&lt;p&gt;" in job.description


async def test_a_big_employer_board_over_5_mb_is_still_read(settings):
    # Databricks, Stripe and Elastic return every posting with its description in one response.
    padding = "x" * (6 * 1024 * 1024)
    job = {"id": 1, "title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/big/jobs/1",
           "location": {"name": "Bengaluru"}, "content": padding}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [job]})

    f = fetcher(handler, {"boards-api.greenhouse.io"})
    result = await GreenhouseConnector().fetch(ctx(settings, f, {"boards": [{"token": "big", "company": "Big"}]}))
    assert [j.external_id for j in result.jobs] == ["1"]
    with pytest.raises(Exception, match="larger than"):  # any other call keeps the 5 MB limit
        await f.get("https://boards-api.greenhouse.io/v1/boards/big/jobs")


async def test_lever_and_ashby(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.lever.co":
            return httpx.Response(200, json=[{"id": "abc", "text": "Full Stack Engineer", "hostedUrl": "https://jobs.lever.co/x/abc",
                                              "categories": {"location": "Bengaluru", "commitment": "Full-time"},
                                              "description": "<p>React and Java</p>", "lists": [{"text": "Requirements", "content": "<li>3+ years of experience</li>"}],
                                              "workplaceType": "hybrid", "createdAt": 1790000000000,
                                              "salaryRange": {"min": 3000000, "max": 4000000, "currency": "INR", "interval": "per-year-salary"}}])
        return httpx.Response(200, json={"jobs": [{"id": "z1", "title": "AI Engineer", "jobUrl": "https://jobs.ashbyhq.com/x/z1",
                                                   "location": "Remote", "isRemote": True, "isListed": True, "descriptionHtml": "<p>LLMs</p>",
                                                   "publishedAt": "2026-10-01T00:00:00Z",
                                                   "compensation": {"summaryComponents": [{"compensationType": "Salary", "minValue": 100000,
                                                                                           "maxValue": 150000, "currencyCode": "USD"}]}},
                                                  {"id": "hidden", "title": "x", "isListed": False}]})

    f = fetcher(handler, {"api.lever.co", "api.ashbyhq.com"})
    lever = (await LeverConnector().fetch(ctx(settings, f, {"boards": [{"token": "x", "company": "X"}]}))).jobs[0]
    assert lever.work_mode == "hybrid" and lever.salary_currency == "INR" and "Requirements" in lever.description
    ashby = (await AshbyConnector().fetch(ctx(settings, f, {"boards": [{"token": "x", "company": "X"}]}))).jobs
    assert len(ashby) == 1 and ashby[0].work_mode == "remote" and ashby[0].salary_currency == "USD"


async def test_invalid_board_tokens_are_ignored(settings):
    assert GreenhouseConnector().configured(ctx(settings, None, {"boards": [{"token": "../../etc"}]}))


async def test_adzuna_requires_credentials(settings):
    with pytest.raises(ConnectorAuthError):
        await AdzunaConnector().fetch(ctx(settings, None, {}))


async def test_safe_fetcher_blocks_unsafe_targets():
    f = fetcher(lambda r: httpx.Response(200), {"api.example.com"})
    with pytest.raises(BlockedURL, match="allowlist"):
        await f.get("https://evil.example.org/x")
    with pytest.raises(BlockedURL, match="https"):
        await f.get("http://api.example.com/x")

    async def private(host: str) -> list[str]:
        return ["169.254.169.254"]

    f.resolver = private
    with pytest.raises(BlockedURL, match="private"):
        await f.get("https://api.example.com/x")


async def test_redirects_are_rechecked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://internal.example.net/admin"})

    with pytest.raises(BlockedURL):
        await fetcher(handler, {"api.example.com"}).get("https://api.example.com/start")


async def test_robots_and_json_ld_career_pages(settings):
    page = """<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
      "title":"Software Engineer","description":"<p>Java, Spring Boot</p>","datePosted":"2026-10-20",
      "hiringOrganization":{"@type":"Organization","name":"Example Inc"},
      "jobLocation":{"@type":"Place","address":{"addressLocality":"Pune","addressCountry":"IN"}},
      "identifier":{"value":"SE-9"},"baseSalary":{"currency":"INR","value":{"minValue":3000000,"maxValue":3800000,"unitText":"YEAR"}}}
      </script></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/")
        return httpx.Response(200, text=page)

    assert job_postings_from_html(page)[0]["title"] == "Software Engineer"
    result = await CareerPageConnector().fetch(ctx(settings, fetcher(handler, set()),
                                                   {"pages": ["https://careers.example.com/jobs", "https://careers.example.com/private/x"]}))
    assert [j.external_id for j in result.jobs] == ["SE-9"]
    assert result.jobs[0].company == "Example Inc" and result.jobs[0].salary_currency == "INR"
    assert any("robots.txt" in w for w in result.warnings)


async def test_connector_failures_are_recorded_and_auth_failures_notify(urt):
    async with urt.sessionmaker() as db:
        await ensure_sources(db, urt.user_id)
        source = await db.scalar(select(JobSource).where(JobSource.key == "mock"))
        source.config = {"scenario": "auth_expired"}
        await db.commit()
    report = await run_discovery(urt, source_key="mock")
    assert report.sources["mock"] == "auth failed"
    async with urt.sessionmaker() as db:
        source = await db.scalar(select(JobSource).where(JobSource.key == "mock"))
        assert source.auth_ok is False and source.last_status == "auth_failed"
        source.config = {"scenario": "down"}
        await db.commit()
    scheduled = await run_discovery(urt, scheduled=True)
    assert "mock" not in scheduled.sources  # an auth-failed source is skipped until you fix and re-test it
    report = await run_discovery(urt, source_key="mock")
    assert report.sources["mock"] == "failed"


# ---------------------------------------------------------------- API security


async def test_csrf_is_required(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            response = await c.post("/api/automation/control", json={"action": "pause"})
            assert response.status_code == 403 and response.json()["error"] == "csrf_failed"


async def test_api_requires_sign_in(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            c.headers["x-csrf-token"] = (await c.get("/api/auth/csrf")).json()["csrf_token"]
            assert (await c.get("/api/dashboard")).status_code == 401
            assert (await c.get("/api/auth/me")).json() == {"authenticated": False, "user": None}


def test_production_configuration_is_validated():
    from cryptography.fernet import Fernet

    good = {"_env_file": None, "environment": "production", "secret_key": "x" * 40, "cookie_secure": True,
            "encryption_keys": Fernet.generate_key().decode(), "public_url": "https://jobs.example.com"}
    ok = Settings(**good)
    assert not ok.mock_enabled  # no demo source or simulated ATS in production
    for missing, message in (("secret_key", "SECRET_KEY"), ("encryption_keys", "ENCRYPTION_KEYS")):
        with pytest.raises(ValueError, match=message):
            Settings(**{k: v for k, v in good.items() if k != missing})
    for override, message in (({"cookie_secure": False}, "COOKIE_SECURE"), ({"public_url": "http://jobs.example.com"}, "PUBLIC_URL"),
                              ({"allow_private_hosts": True}, "ALLOW_PRIVATE_HOSTS")):
        with pytest.raises(ValueError, match=message):
            Settings(**{**good, **override})


async def test_automatic_mode_needs_the_confirmation_phrase(client):
    policy = (await client.get("/api/automation")).json()
    body = {"policy": policy["policy"] | {"mode": "automatic"}}
    refused = await client.put("/api/automation", json=body)
    assert refused.status_code == 422 and "ENABLE AUTOMATIC MODE" in refused.json()["message"]
    assert (await client.get("/api/automation")).json()["policy"]["mode"] == "supervised"
    accepted = await client.put("/api/automation", json=body | {"confirmation": policy["confirmation_phrase"]})
    assert accepted.json()["policy"]["mode"] == "automatic"
    audit = (await client.get("/api/audit", params={"action": "config.mode"})).json()["items"]
    assert audit and "ENABLED" in audit[0]["message"]


async def test_csv_export_neutralises_formulas(client):
    await client.post("/api/jobs/import", json={"title": "=HYPERLINK(\"evil\")", "company": "+Corp",
                                                "url": "https://x.example.com/1", "description": "Requirements\n- Java and Spring Boot for 3+ years"})
    text = (await client.get("/api/jobs/export.csv")).text
    assert "'=HYPERLINK" in text and "'+Corp" in text


async def test_integrations_never_return_secret_values(client, sessionmaker):
    saved = await client.put("/api/integrations/adzuna", json={"config": {"app_id": "id-123"},
                                                               "secrets": {"app_key": "super-secret-key"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["secrets_set"] == ["app_key"]
    body = (await client.get("/api/integrations")).text
    assert "super-secret-key" not in body and json.loads(body)["unsupported"]
    from hirefinch.db import UserIntegration

    async with sessionmaker() as db:
        row = await db.scalar(select(UserIntegration))
        assert "super-secret-key" not in (row.secret or "")  # encrypted at rest
    kept = await client.put("/api/integrations/adzuna", json={"config": {"app_id": "id-456"}, "secrets": {"app_key": ""}})
    assert kept.json()["secrets_set"] == ["app_key"]  # blank keeps the stored secret


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("HIREFINCH_LIVE_TESTS") != "1", reason="set HIREFINCH_LIVE_TESTS=1 to call real APIs")
async def test_live_greenhouse_board(settings):
    """Read-only call to a public Greenhouse board. Never applies or sends anything."""
    async with httpx.AsyncClient(timeout=20) as client:
        f = SafeFetcher(client, allowed_hosts=frozenset({"boards-api.greenhouse.io"}), user_agent=settings.http_user_agent)
        token = os.environ.get("HIREFINCH_LIVE_GREENHOUSE_BOARD", "gitlab")
        result = await GreenhouseConnector().fetch(ctx(settings, f, {"boards": [{"token": token, "company": token}]}))
    assert result.jobs or result.warnings



async def test_board_location_filter(settings):
    locations = ["Bangalore, India", "San Francisco, CA", "Remote - India", "Remote - US", "Hyderabad, India",
                 "Navi Mumbai", ""]

    def handler(request: httpx.Request) -> httpx.Response:
        jobs = [{"id": i, "title": "Backend Engineer", "absolute_url": f"https://x.example/{i}", "content": "Java",
                 "location": {"name": loc}} for i, loc in enumerate(locations)]
        return httpx.Response(200, json={"jobs": jobs})

    config = {"boards": [{"token": "acme", "company": "Acme"}],
              "locations": ["Mumbai", "Navi Mumbai", "Pune", "Bengaluru"], "remote_country": "India"}
    result = await GreenhouseConnector().fetch(ctx(settings, fetcher(handler, {"boards-api.greenhouse.io"}), config))
    assert [j.location for j in result.jobs] == ["Bangalore, India", "Remote - India", "Navi Mumbai", ""]


async def test_gzip_responses_are_decoded_once():
    import gzip

    body = gzip.compress(json.dumps({"jobs": []}).encode())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-encoding": "gzip", "content-type": "application/json"})

    response = await fetcher(handler, {"api.example.com"}).get("https://api.example.com/jobs")
    assert response.json() == {"jobs": []}


def test_llm_temperature_override(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.2")
    base = Settings(_env_file=None, environment="test")
    assert base.llm_settings().llm_temperature == 0.2
    none = Settings(_env_file=None, environment="test", llm_provider="openai_compatible", llm_temperature="none")
    assert none.llm_settings().llm_temperature is None  # GPT-5.x rejects a custom temperature
    assert none.llm_settings().llm_provider == "openai_compatible"
    assert Settings(_env_file=None, environment="test", llm_temperature="0.5").llm_settings().llm_temperature == 0.5
