"""Every job source the agent knows about, including the ones it deliberately does not automate.

The major Indian and international job boards either offer no public job-search API to
individuals or forbid automated access in their terms, and several sit behind login walls and
anti-bot checks. The agent does not scrape them. For those, open the posting yourself and use
"Import job" (paste the description and URL); everything downstream then works the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .aggregators import JoobleConnector, TheMuseConnector
from .ats import AshbyConnector, GreenhouseConnector, LeverConnector, SmartRecruitersConnector
from .base import Connector, Support
from .job_alerts import JobAlertsConnector
from .mock import MockConnector
from .web import AdzunaConnector, CareerPageConnector


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    support: Support
    description: str
    connector: type[Connector] | None = None
    env_vars: tuple[str, ...] = ()
    default_config: dict = field(default_factory=dict)
    default_enabled: bool = False


CATALOG: tuple[SourceSpec, ...] = (
    SourceSpec("mock", "Mock jobs (demo)", Support.IMPLEMENTED,
               "Bundled sample postings for trying the full workflow; no network.", MockConnector, default_enabled=True),
    SourceSpec("greenhouse", "Greenhouse job boards", Support.IMPLEMENTED,
               "Official public Job Board API. Add companies by board token, e.g. {\"token\": \"stripe\", \"company\": \"Stripe\"}.",
               GreenhouseConnector, default_config={"boards": []}),
    SourceSpec("lever", "Lever job boards", Support.IMPLEMENTED,
               "Official public Postings API. Add companies by site name from jobs.lever.co/<site>.",
               LeverConnector, default_config={"boards": []}),
    SourceSpec("ashby", "Ashby job boards", Support.IMPLEMENTED,
               "Official public Job Board API. Add companies by board name from jobs.ashbyhq.com/<name>.",
               AshbyConnector, default_config={"boards": []}),
    SourceSpec("smartrecruiters", "SmartRecruiters job boards", Support.IMPLEMENTED,
               "Official public Posting API (used by Freshworks, Swiggy and many others). Add companies by the id "
               "in jobs.smartrecruiters.com/<id>.", SmartRecruitersConnector, default_config={"boards": []}),
    SourceSpec("career_page", "Company career pages", Support.IMPLEMENTED,
               "Reads schema.org JobPosting data from career pages you list. Honours robots.txt.",
               CareerPageConnector, default_config={"pages": []}),
    SourceSpec("adzuna", "Adzuna job search", Support.NEEDS_CREDENTIALS,
               "Official search API with Indian coverage (free developer key). Descriptions are snippets.",
               AdzunaConnector, ("adzuna",),  # credentials: the user's Adzuna integration
               default_config={"country": "in", "queries": [], "max_days_old": 7}),
    SourceSpec("jooble", "Jooble job search", Support.NEEDS_CREDENTIALS,
               "Official partner API aggregating many Indian job sites (free key from jooble.org/api/about). "
               "Searches your target roles in your locations; descriptions are snippets.",
               JoobleConnector, ("jooble",), default_config={"queries": [], "locations": ["India"]}),
    SourceSpec("themuse", "The Muse", Support.IMPLEMENTED,
               "Public jobs API, mostly US and remote roles. Listings credit The Muse and link to its page.",
               TheMuseConnector, default_config={"categories": ["Software Engineering"], "pages": 3}),
    SourceSpec("job_alerts", "LinkedIn, Naukri, Indeed & Hirist job alerts", Support.NEEDS_CREDENTIALS,
               "Reads the job-alert emails these sites send you (read-only IMAP, nothing is changed). "
               "Create alerts on those sites, then connect your mailbox in Integrations.",
               JobAlertsConnector, ("imap",), default_config={"sites": ["linkedin", "naukri", "indeed", "hirist"],
                                                             "folder": "INBOX"}),
    SourceSpec("manual", "Manual import", Support.MANUAL,
               "Paste a job you found anywhere (LinkedIn, Naukri, ...). Always available on the Jobs page."),
    SourceSpec("linkedin", "LinkedIn Jobs", Support.MANUAL,
               "No public search API and scraping is forbidden. Covered by the job-alerts source: create alerts on LinkedIn and connect your mailbox. Or paste a posting with Import."),
    SourceSpec("naukri", "Naukri.com", Support.MANUAL,
               "No public search API and scraping is forbidden. Covered by the job-alerts source: create alerts on Naukri.com and connect your mailbox. Or paste a posting with Import."),
    SourceSpec("indeed", "Indeed", Support.MANUAL,
               "No public search API and scraping is forbidden. Covered by the job-alerts source: create alerts on Indeed and connect your mailbox. Or paste a posting with Import."),
    SourceSpec("glassdoor", "Glassdoor", Support.UNSUPPORTED, "No public jobs API; login wall. Use manual import."),
    SourceSpec("foundit", "Foundit (Monster India)", Support.UNSUPPORTED, "No public API. Use manual import."),
    SourceSpec("hirist", "Hirist", Support.MANUAL,
               "No public search API. Covered by the job-alerts source: create alerts on Hirist and connect your mailbox."),
    SourceSpec("instahyre", "Instahyre", Support.UNSUPPORTED, "Login-only platform, no public API. Use manual import."),
    SourceSpec("cutshort", "Cutshort", Support.UNSUPPORTED, "Login-only platform, no public API. Use manual import."),
    SourceSpec("wellfound", "Wellfound (AngelList Talent)", Support.UNSUPPORTED,
               "No public API; anti-bot protection. Many startups listed there use Greenhouse, Lever or Ashby: add them there."),
    SourceSpec("google_jobs", "Google Jobs", Support.UNSUPPORTED,
               "No official API. Career pages that appear in Google Jobs publish JobPosting data: add them as career pages."),
)

BY_KEY = {s.key: s for s in CATALOG}
API_HOSTS = frozenset(h for s in CATALOG if s.connector for h in s.connector.api_hosts)
