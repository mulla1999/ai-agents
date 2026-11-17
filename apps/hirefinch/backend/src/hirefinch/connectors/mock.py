"""Mock job source backed by bundled fixtures, for demos and tests. Never touches the network."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from ..domain import RawJob
from .base import Connector, ConnectorAuthError, ConnectorError, FetchResult, SourceContext

FIXTURES = Path(__file__).parent / "fixtures" / "mock_jobs.json"


class MockConnector(Connector):
    kind = "mock"

    async def fetch(self, ctx: SourceContext) -> FetchResult:
        scenario = ctx.config.get("scenario")
        if scenario == "auth_expired":
            raise ConnectorAuthError("mock source: credentials expired")
        if scenario == "down":
            raise ConnectorError("mock source: service unavailable")
        items = json.loads(FIXTURES.read_text())
        only = set(ctx.config.get("only", []))
        jobs = []
        for item in items:
            if only and item["external_id"] not in only:
                continue
            item = dict(item)
            days = item.pop("posted_days_ago", 0)
            behavior = item.pop("mock_behavior", None)
            job = RawJob(**item, posted_at=date.today() - timedelta(days=days), is_active=True)
            if behavior:
                job.extra["mock_behavior"] = behavior
            jobs.append(job)
        return FetchResult(jobs)
