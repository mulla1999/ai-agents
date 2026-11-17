"""Find a company's job board by name or careers link, and follow it."""

from __future__ import annotations

import httpx

from hirefinch.net import SafeFetcher
from hirefinch.services import company_finder


async def public(host: str) -> list[str]:
    return ["93.184.216.34"]


def fetcher(handler) -> SafeFetcher:
    return SafeFetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), allowed_hosts=frozenset(),
                       user_agent="t", min_interval=0, resolver=public, max_retries=0)


def test_names_and_links_become_board_ids():
    assert company_finder.candidates("Razorpay Software Pvt Ltd")[0][0] == "razorpay"
    assert "observe-ai" in company_finder.candidates("Observe AI")[0]
    assert company_finder.candidates("https://jobs.lever.co/cred/abc-123") == (["cred"], "lever")
    assert company_finder.candidates("boards.greenhouse.io/stripe") == (["stripe"], "greenhouse")
    assert company_finder.candidates("Booking.com")[0][0] == "booking"  # a site name, not a board link


async def test_finds_the_boards_that_exist_and_counts_india_jobs():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        path = request.url.path
        if path == "/v1/boards/acme/jobs":
            return httpx.Response(200, json={"jobs": [{"company_name": "Acme", "location": {"name": "Bengaluru, India"}},
                                                      {"company_name": "Acme", "location": {"name": "London"}}]})
        if path == "/v1/boards/acme":
            return httpx.Response(200, json={"name": "Acme Corp"})
        if path == "/v1/companies/acme/postings":
            return httpx.Response(200, json={"totalFound": 0, "content": []})  # answers for any name
        return httpx.Response(404, json={})

    results = await company_finder.find(fetcher(handler), "Acme")
    assert results == [{"kind": "greenhouse", "token": "acme", "company": "Acme Corp", "jobs": 2, "india_jobs": 1}]
    assert {"boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com", "api.smartrecruiters.com"} <= set(seen)


async def test_add_a_found_company_to_a_source(client):
    r = await client.post("/api/sources/lever/boards", json={"token": "cred", "company": "CRED"})
    assert r.status_code == 200, r.text
    lever = next(s for s in r.json() if s["key"] == "lever")
    assert lever["enabled"] and {"token": "cred", "company": "CRED"} in lever["config"]["boards"]
    again = await client.post("/api/sources/lever/boards", json={"token": "CRED", "company": "CRED"})
    assert [b["token"].lower() for b in next(s for s in again.json() if s["key"] == "lever")["config"]["boards"]].count("cred") == 1
    bad = await client.post("/api/sources/lever/boards", json={"token": "no spaces allowed", "company": "X"})
    assert bad.status_code == 422
    assert (await client.post("/api/sources/jooble/boards", json={"token": "x", "company": "X"})).status_code == 400
