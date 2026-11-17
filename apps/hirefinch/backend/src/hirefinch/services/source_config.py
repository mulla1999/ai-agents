"""Checks a job source's settings when you save them, so a typo is reported at once instead of the
source silently skipping it at the next discovery run.

Each source accepts only the settings it reads. Board tokens must look like the board's id (they go
into the board API's URL), and career pages must be full https links.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..errors import ServiceError

_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,80}")
_BOARDS = ("greenhouse", "lever", "ashby", "smartrecruiters")
ALLOWED: dict[str, set[str]] = {
    **{k: {"boards", "locations", "remote_country"} for k in _BOARDS},
    "career_page": {"pages"},
    "adzuna": {"country", "queries", "max_days_old", "results_per_page", "where"},
    "jooble": {"queries", "locations", "max_requests_per_run"},
    "themuse": {"categories", "pages", "locations"},
    "job_alerts": {"sites", "folder"},
    "mock": {"scenario", "only"},
}
ALLOWED["lever"] |= {"region"}
ALERT_SITES = {"linkedin", "naukri", "indeed", "hirist"}
ADZUNA_COUNTRIES = {"in", "gb", "us", "au", "ca", "de", "fr", "nl", "sg", "nz", "za", "br", "at", "be", "ch", "es", "it", "mx", "pl"}


def _bad(message: str) -> ServiceError:
    return ServiceError("invalid_config", message, 422)


def _strings(config: dict[str, Any], key: str, *, max_items: int, max_len: int = 100) -> None:
    value = config.get(key)
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _bad(f"“{key}” must be a list of text, e.g. [\"Pune\", \"Bengaluru\"]")
    cleaned = [" ".join(v.split()) for v in value if v.strip()]
    if len(cleaned) > max_items or any(len(v) > max_len for v in cleaned):
        raise _bad(f"“{key}”: at most {max_items} entries of up to {max_len} characters")
    config[key] = cleaned


def _int(config: dict[str, Any], key: str, lo: int, hi: int) -> None:
    value = config.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi):
        raise _bad(f"“{key}” must be a whole number from {lo} to {hi}")


def validate_source_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return the cleaned config or raise ServiceError(422) naming the problem."""
    if not isinstance(config, dict):
        raise _bad("the configuration must be a JSON object")
    allowed = ALLOWED.get(kind, set())
    if unknown := set(config) - allowed:
        raise _bad(f"unknown setting {', '.join(sorted(unknown))} for this source; allowed: {', '.join(sorted(allowed)) or 'none'}")
    config = dict(config)
    if kind in _BOARDS:
        boards = config.get("boards") or []
        if not isinstance(boards, list):
            raise _bad("“boards” must be a list like [{\"token\": \"stripe\", \"company\": \"Stripe\"}]")
        seen, clean = set(), []
        for i, b in enumerate(boards, 1):
            if not isinstance(b, dict) or set(b) - {"token", "company"}:
                raise _bad(f"board {i}: use {{\"token\": \"…\", \"company\": \"…\"}}")
            token = str(b.get("token") or "").strip()
            if not _TOKEN.fullmatch(token):
                raise _bad(f"board {i}: “{token[:40]}” is not a board id (letters, digits, '.', '_' and '-' only, "
                           "as in the board's own link)")
            if token.lower() in seen:
                raise _bad(f"board “{token}” is listed twice")
            seen.add(token.lower())
            company = " ".join(str(b.get("company") or token).split())[:120]
            clean.append({"token": token, "company": company})
        config["boards"] = clean
        _strings(config, "locations", max_items=30, max_len=80)
        if (rc := config.get("remote_country")) is not None and (not isinstance(rc, str) or len(rc) > 60):
            raise _bad("“remote_country” must be a country name, e.g. \"India\"")
        if "region" in config and config["region"] not in ("us", "eu"):
            raise _bad("“region” must be \"us\" or \"eu\"")
    elif kind == "career_page":
        pages = config.get("pages") or []
        if not isinstance(pages, list) or not all(isinstance(p, str) for p in pages):
            raise _bad("“pages” must be a list of links, e.g. [\"https://careers.example.com/jobs\"]")
        clean = []
        for page in (p.strip() for p in pages):
            parts = urlsplit(page)
            if parts.scheme != "https" or not parts.hostname or "." not in parts.hostname or len(page) > 500:
                raise _bad(f"“{page[:60]}” is not a full https:// link")
            if page not in clean:
                clean.append(page)
        config["pages"] = clean
    elif kind == "adzuna":
        if "country" in config and config["country"] not in ADZUNA_COUNTRIES:
            raise _bad(f"“country” must be one of Adzuna's codes: {', '.join(sorted(ADZUNA_COUNTRIES))}")
        _strings(config, "queries", max_items=20)
        _int(config, "max_days_old", 1, 90)
        _int(config, "results_per_page", 1, 50)
        if (where := config.get("where")) is not None and (not isinstance(where, str) or len(where) > 80):
            raise _bad("“where” must be a place name of up to 80 characters")
    elif kind == "jooble":
        _strings(config, "queries", max_items=20)
        _strings(config, "locations", max_items=20, max_len=80)
        _int(config, "max_requests_per_run", 1, 30)  # a free key has a fixed allowance
    elif kind == "themuse":
        _strings(config, "categories", max_items=20, max_len=80)
        _strings(config, "locations", max_items=30, max_len=80)
        _int(config, "pages", 1, 10)
    elif kind == "job_alerts":
        sites = config.get("sites")
        if sites is not None and (not isinstance(sites, list) or not sites or set(sites) - ALERT_SITES):
            raise _bad(f"“sites” must list some of: {', '.join(sorted(ALERT_SITES))}")
        if (folder := config.get("folder")) is not None and (not isinstance(folder, str) or not 1 <= len(folder) <= 100):
            raise _bad("“folder” must be a mailbox folder name, e.g. \"INBOX\"")
    return config
