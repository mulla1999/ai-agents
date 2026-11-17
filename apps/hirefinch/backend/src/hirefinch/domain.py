"""Typed contracts passed between components: profile, preferences, policy, resume and job models.

The profile, preferences and policy are stored as validated JSON in the database and edited in the
UI. Defaults are safe: supervised mode, no automatic applications, no automatic outreach.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationInfo, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- profile & preferences


class VerifiedSkill(Strict):
    """A skill you have but your resume does not mention, with where it can be verified."""

    name: str = Field(min_length=1, max_length=80)
    evidence: str = Field(min_length=3, max_length=500)


def _saving(info: ValidationInfo) -> bool:
    """True when validating new input; False when loading what is already stored. Rules added after
    data was saved apply to saves only, so an old value never blanks a profile on load."""
    return not (info.context or {}).get("stored")


def _clean_list(values: list[str], *, label: str, max_items: int = 50, max_len: int = 100) -> list[str]:
    """Trimmed, de-duplicated (case-insensitive), no blanks; raises when too long."""
    out, seen = [], set()
    for v in values:
        v = " ".join(str(v).split())
        if v and v.lower() not in seen:
            if len(v) > max_len:
                raise ValueError(f"{label}: “{v[:30]}…” is longer than {max_len} characters")
            seen.add(v.lower())
            out.append(v)
    if len(out) > max_items:
        raise ValueError(f"{label}: at most {max_items} entries")
    return out


# CTC is in lakhs per annum (1 LPA = ₹1,00,000). Anything above this is almost certainly a rupee
# amount typed into an LPA field (₹12,49,000 entered as 1249000).
MAX_CTC_LPA = 500.0


def plausible_lpa(value: float | None) -> float | None:
    """The value when it can be a CTC in LPA, else None: the agent then asks instead of using it."""
    return value if value is not None and 0 < value <= MAX_CTC_LPA else None


def _inr(value: float) -> str:
    """Indian digit grouping: 1249000 -> 12,49,000."""
    digits = f"{value:.0f}"
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail])


def ctc_problem(value: float) -> str | None:
    if value <= 0:
        return "enter a CTC above 0, in lakhs per annum (LPA), e.g. 12.5"
    if value > MAX_CTC_LPA:
        return (f"{_inr(value)} looks like rupees. Enter lakhs per annum (LPA): "
                f"₹{_inr(value)} is {value / 100000:.2f} LPA")
    return None


EMAIL_PLACEHOLDERS = ("greeting", "first_name", "job_title", "company", "job_url", "current_title", "current_company",
                      "years", "skills", "projects", "qualifications", "attachment_note", "signature", "name")


class EmailStyle(Strict):
    """How the agent writes recruiter emails for you. Nothing about the format is fixed in code: with an
    AI provider the agent writes each email in this tone; without one it fills your template."""

    tone: Literal["professional", "warm", "concise", "enthusiastic"] = "professional"
    length: Literal["short", "medium"] = "short"
    # Sign-off block under the email. Empty: your name, email, phone and LinkedIn from the profile.
    signature: str | None = Field(default=None, max_length=600)
    # Optional template with {placeholders}; see services/email_compose.PLACEHOLDERS. Empty: built-in layout.
    template: str | None = Field(default=None, max_length=4000)
    subject_template: str | None = Field(default=None, max_length=200)
    html: bool = True  # also send a formatted (HTML) version next to the plain text

    @field_validator("template", "subject_template")
    @classmethod
    def _known_placeholders(cls, value: str | None) -> str | None:
        if value:
            import string

            try:
                fields = {f for _, f, _, _ in string.Formatter().parse(value) if f is not None}
            except ValueError as exc:
                raise ValueError("unbalanced { or } in the template; write {{ or }} for a literal brace") from exc
            if "" in fields or (unknown := fields - set(EMAIL_PLACEHOLDERS)):
                raise ValueError(f"unknown placeholders: {', '.join(sorted(unknown or set()) or ['{}'])}. "
                                 f"Use: {', '.join(EMAIL_PLACEHOLDERS)}")
        return value


class SelfIdentification(Strict):
    """Answers to equal-opportunity and personal questions, exactly as you want them given. They are
    never inferred from your name or resume. Leave one empty and that question waits for you; write
    "Prefer not to say" to decline on every form."""

    gender: str | None = Field(default=None, max_length=60)
    pronouns: str | None = Field(default=None, max_length=40)
    ethnicity: str | None = Field(default=None, max_length=80)
    disability: str | None = Field(default=None, max_length=60)  # e.g. "No", "Yes", "Prefer not to say"
    veteran: str | None = Field(default=None, max_length=60)
    date_of_birth: date | None = None


class CommonAnswers(Strict):
    """Questions most application forms ask. Empty means: ask me on the form."""

    country_of_residence: str | None = Field(default=None, max_length=60)
    highest_education: str | None = Field(default=None, max_length=120)  # empty: taken from your resume
    managed_team: bool | None = None
    willing_onsite: bool | None = None
    background_check_consent: bool | None = None
    criminal_record: bool | None = None  # "have you ever been convicted…"
    how_did_you_hear: str | None = Field(default=None, max_length=80)
    # Tick "I certify the information is accurate / I agree to the privacy notice" boxes for you.
    accept_declarations: bool = False


class Profile(Strict):
    """Facts about you that are not on the resume, all optional. Unknown stays unknown: the agent
    pauses instead of guessing when a form needs one of these."""

    full_name: str | None = None
    headline: str | None = None
    contact_email: EmailStr | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None
    notification_email: EmailStr | None = None

    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    current_ctc_lpa: float | None = None  # lakhs per annum; see MAX_CTC_LPA
    expected_ctc_lpa: float | None = None
    authorized_to_work_in: list[str] = Field(default_factory=list)  # e.g. ["India"]
    requires_sponsorship: bool | None = None
    willing_to_relocate: bool | None = None
    count_internships_as_experience: bool = False

    verified_extra_skills: list[VerifiedSkill] = Field(default_factory=list)
    # Skills a job asked for that you said you don't have, so HireFinch doesn't ask again.
    declined_skills: list[str] = Field(default_factory=list)
    # Answers you have confirmed for recurring application questions, keyed by a short label.
    custom_answers: dict[str, str] = Field(default_factory=dict)
    email_style: EmailStyle = Field(default_factory=EmailStyle)
    self_identification: SelfIdentification = Field(default_factory=SelfIdentification)
    common_answers: CommonAnswers = Field(default_factory=CommonAnswers)

    @field_validator("full_name", "headline", "location", "phone", "linkedin_url", "portfolio_url", mode="before")
    @classmethod
    def _blank_is_none(cls, value):  # noqa: ANN001, ANN206
        if isinstance(value, str):
            value = " ".join(value.split())
            return value or None
        return value

    @model_validator(mode="after")
    def _checked_on_save(self, info: ValidationInfo) -> Profile:
        import re

        if not _saving(info):
            return self
        for name, limit in (("full_name", 120), ("headline", 200), ("location", 120)):
            if (v := getattr(self, name)) and len(v) > limit:
                raise ValueError(f"{name.replace('_', ' ')}: at most {limit} characters")
        if self.phone:
            digits = re.sub(r"\D", "", self.phone)
            if not re.fullmatch(r"\+?[0-9 ()\-.]{7,22}", self.phone) or not 7 <= len(digits) <= 15:
                raise ValueError("phone: use digits with an optional +country code, e.g. +91 98765 43210")
        if self.linkedin_url and not re.fullmatch(r"https://([a-z]{2,3}\.)?linkedin\.com/(in|pub)/[A-Za-z0-9_%\-]{2,100}/?", self.linkedin_url):
            raise ValueError("LinkedIn URL: use your profile link, e.g. https://www.linkedin.com/in/your-name")
        if self.portfolio_url:
            from urllib.parse import urlsplit

            parts = urlsplit(self.portfolio_url)
            if parts.scheme not in ("https", "http") or not parts.hostname or "." not in parts.hostname or len(self.portfolio_url) > 300:
                raise ValueError("portfolio URL: use a full link, e.g. https://github.com/your-name")
        self.authorized_to_work_in = _clean_list(self.authorized_to_work_in, label="authorised to work in", max_items=20, max_len=60)
        if len(self.verified_extra_skills) > 50:
            raise ValueError("verified extra skills: at most 50")
        self.declined_skills = _clean_list(self.declined_skills, label="skills you don't have", max_items=200, max_len=80)
        names = [x.name.strip().lower() for x in self.verified_extra_skills]
        if len(names) != len(set(names)):
            raise ValueError("verified extra skills: each skill only once")
        if len(self.custom_answers) > 50:
            raise ValueError("confirmed answers: at most 50")
        for key, answer in self.custom_answers.items():
            if not key.strip() or len(key) > 100 or len(answer) > 2000:
                raise ValueError("confirmed answers: keyword up to 100 characters, answer up to 2000")
        return self

    @field_validator("current_ctc_lpa", "expected_ctc_lpa")
    @classmethod
    def _ctc_in_lpa(cls, value: float | None, info: ValidationInfo) -> float | None:
        # Values already stored load as they are (a bad one must not blank the whole profile);
        # every save is checked. The agent ignores an implausible stored value (plausible_lpa).
        if value is None or (info.context or {}).get("stored"):
            return value
        if problem := ctc_problem(value):
            raise ValueError(problem)
        return round(value, 2)


WorkMode = Literal["remote", "hybrid", "onsite"]


class ScoreWeights(Strict):
    technical: float = Field(default=30, ge=0)
    experience: float = Field(default=25, ge=0)
    role: float = Field(default=15, ge=0)
    domain: float = Field(default=10, ge=0)
    location: float = Field(default=10, ge=0)
    compensation: float = Field(default=10, ge=0)

    @model_validator(mode="after")
    def _not_all_zero(self) -> ScoreWeights:
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("at least one score weight must be positive")
        return self


class Thresholds(Strict):
    high: int = Field(default=85, ge=0, le=100)
    good: int = Field(default=70, ge=0, le=100)
    review: int = Field(default=55, ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if not self.high >= self.good >= self.review:
            raise ValueError("thresholds must satisfy high >= good >= review")
        return self


class Preferences(Strict):
    target_roles: list[str] = Field(
        default_factory=lambda: [
            "Full Stack Engineer",
            "Software Engineer",
            "Backend Engineer",
            "Java Developer",
            "AI Engineer",
            "AI Agent Engineer",
            "GenAI Engineer",
            "Applied AI Engineer",
            "Platform Engineer",
        ]
    )
    min_compensation_lpa: float | None = Field(default=30, ge=0)
    target_compensation_lpa: tuple[float, float] | None = (30, 40)
    # Rates to convert published non-INR salaries; without a rate such salaries count as unknown.
    fx_rates_to_inr: dict[str, float] = Field(default_factory=dict)
    preferred_locations: list[str] = Field(default_factory=lambda: ["Bengaluru", "Mumbai", "Pune", "Thane", "Remote"])
    work_modes: list[WorkMode] = Field(default_factory=lambda: ["remote", "hybrid", "onsite"])
    onsite_only_in_preferred_locations: bool = True
    target_companies: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    max_experience_gap_years: float = Field(default=2.0, ge=0)
    # Discovery keeps only jobs published within this many days (None = any age). Jobs without a
    # publish date are skipped unless include_undated is on. Manual imports are always kept.
    max_posting_age_days: int | None = Field(default=3, ge=1, le=90)
    include_undated: bool = False
    weights: ScoreWeights = Field(default_factory=ScoreWeights)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @model_validator(mode="after")
    def _checked_on_save(self, info: ValidationInfo) -> Preferences:
        import re

        if not _saving(info):
            return self
        for name in ("target_roles", "preferred_locations", "target_companies", "excluded_companies", "excluded_keywords"):
            setattr(self, name, _clean_list(getattr(self, name), label=name.replace("_", " ")))
        if not self.target_roles:
            raise ValueError("target roles: add at least one role to search for")
        if not self.work_modes:
            raise ValueError("work modes: accept at least one of remote, hybrid or on-site")
        self.work_modes = list(dict.fromkeys(self.work_modes))
        if self.min_compensation_lpa is not None and self.min_compensation_lpa > 0 and (problem := ctc_problem(self.min_compensation_lpa)):
            raise ValueError(f"minimum compensation: {problem}")
        if self.target_compensation_lpa is not None:
            lo, hi = self.target_compensation_lpa
            for v in (lo, hi):
                if v and (problem := ctc_problem(v)):
                    raise ValueError(f"target compensation: {problem}")
            if lo > hi:
                raise ValueError("target compensation: the first number (from) must not be above the second (to)")
            if self.min_compensation_lpa and hi and self.min_compensation_lpa > hi:
                raise ValueError("minimum compensation is above your target range")
        for code, rate in self.fx_rates_to_inr.items():
            if not re.fullmatch(r"[A-Z]{3}", code) or not 0 < rate <= 100000:
                raise ValueError("exchange rates: 3-letter currency codes with a positive rate, e.g. USD=84")
        if self.max_experience_gap_years > 20:
            raise ValueError("allowed experience gap: at most 20 years")
        return self


class ApplicationMode(StrEnum):
    SUPERVISED = "supervised"
    AUTOMATIC = "automatic"


NOTIFY_KINDS = ("application_submitted", "application_uncertain", "application_failed", "outreach_sent", "approval_required",
                "resume_ready", "high_priority_job", "daily_summary", "connector_auth_expired", "automation_stopped")


class AutomationPolicy(Strict):
    mode: ApplicationMode = ApplicationMode.SUPERVISED
    shortlist_min_score: int = Field(default=70, ge=0, le=100)
    tailor_min_score: int = Field(default=70, ge=0, le=100)
    auto_apply_min_score: int = Field(default=85, ge=0, le=100)
    auto_apply_routes: list[str] = Field(default_factory=lambda: ["email"])
    daily_application_limit: int = Field(default=5, ge=0, le=100)
    weekly_application_limit: int = Field(default=20, ge=0, le=500)
    auto_send_outreach: bool = False
    outreach_daily_limit: int = Field(default=3, ge=0, le=50)
    use_llm_for_tailoring: bool = False
    discovery_interval_minutes: int = Field(default=360, ge=15)
    digest_hour_local: int = Field(default=20, ge=0, le=23)
    timezone: str = "Asia/Kolkata"
    # Pacing for automatic actions (see workflow/timing.py). Days: 0 = Monday.
    send_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    send_windows: list[str] = Field(default_factory=lambda: ["09:30-12:30", "14:00-16:30"])
    auto_review_minutes: int = Field(default=60, ge=0, le=1440)  # time to look and cancel before it goes out
    discovery_hours: str = "06:00-22:00"
    max_bullets_older_roles: int = Field(default=4, ge=1, le=12)
    notify: list[str] = Field(default_factory=lambda: list(NOTIFY_KINDS))

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone, e.g. Asia/Kolkata") from exc
        return value

    @field_validator("send_days")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if not value or any(d not in range(7) for d in value):
            raise ValueError("send days are 0 (Monday) to 6 (Sunday), at least one")
        return sorted(set(value))

    @field_validator("send_windows", "discovery_hours")
    @classmethod
    def _windows(cls, value):  # noqa: ANN001, ANN206
        import re

        items = value if isinstance(value, list) else [value]
        for item in items:
            m = re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d", item.strip())
            if not m:
                raise ValueError("use HH:MM-HH:MM, e.g. 09:30-12:30")
            if isinstance(value, list) and item.split("-")[0] >= item.split("-")[1]:
                raise ValueError("a send window must end after it starts")
        if isinstance(value, list) and not value:
            raise ValueError("add at least one send window")
        return value

    @field_validator("auto_apply_min_score")
    @classmethod
    def _auto_floor(cls, value: int) -> int:
        if value < 70:
            raise ValueError("automatic applications need a minimum score of at least 70")
        return value

    @model_validator(mode="after")
    def _checked_on_save(self, info: ValidationInfo) -> AutomationPolicy:
        if not _saving(info):
            return self
        known_routes = {"email", "mock"}  # applications.policy.AUTOMATABLE_ROUTES: manual is never automatic
        if bad := set(self.auto_apply_routes) - known_routes:
            raise ValueError(f"automatic routes: only email (or mock in demo mode); not {', '.join(sorted(bad))}")
        if bad := set(self.notify) - set(NOTIFY_KINDS):
            raise ValueError(f"notifications: unknown kind {', '.join(sorted(bad))}")
        if self.weekly_application_limit < self.daily_application_limit:
            raise ValueError("weekly application limit must be at least the daily limit")
        if self.discovery_interval_minutes > 10080:
            raise ValueError("discovery interval: at most 10080 minutes (one week)")
        if len(self.send_windows) > 6:
            raise ValueError("send windows: at most 6")
        self.auto_apply_routes = list(dict.fromkeys(self.auto_apply_routes))
        self.notify = list(dict.fromkeys(self.notify))
        return self


# ---------------------------------------------------------------- resume


class Bullet(Strict):
    id: str
    text: str
    # Set on a tailored bullet that was reworded: the master bullet it came from. The validator checks
    # the wording against it (resume.validator.rewrite_problem).
    source: str | None = None


class ExperienceEntry(Strict):
    id: str
    title: str
    company: str
    location: str | None = None
    start: date | None = None
    end: date | None = None  # None with is_current=True means "Present"
    is_current: bool = False
    date_text: str = ""
    is_internship: bool = False
    bullets: list[Bullet] = Field(default_factory=list)


class ProjectEntry(Strict):
    id: str
    name: str
    subtitle: str | None = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[Bullet] = Field(default_factory=list)


class SkillGroup(Strict):
    name: str
    items: list[str]


class Contact(Strict):
    name: str = ""
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class ExtraSection(Strict):
    title: str
    lines: list[str]


class ResumeDocument(Strict):
    """Structured resume. The master is parsed once and kept; tailored versions are derived from it."""

    contact: Contact = Field(default_factory=Contact)
    summary: str = ""
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    extra_sections: list[ExtraSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def all_bullets(self) -> list[Bullet]:
        return [b for e in self.experience for b in e.bullets] + [b for p in self.projects for b in p.bullets]

    def full_text(self) -> str:
        parts = [self.contact.headline or "", self.summary]
        parts += [f"{g.name}: {', '.join(g.items)}" for g in self.skills]
        for e in self.experience:
            parts += [e.title, e.company] + [b.text for b in e.bullets]
        for p in self.projects:
            parts += [p.name, p.subtitle or "", " · ".join(p.technologies)] + [b.text for b in p.bullets]
        parts += self.education + self.certifications
        parts += [line for s in self.extra_sections for line in s.lines]
        return "\n".join(x for x in parts if x)


# ---------------------------------------------------------------- jobs


class RawJob(BaseModel):
    """What a connector returns, before normalisation. Everything here is untrusted input."""

    external_id: str
    url: str
    title: str
    company: str
    description: str  # HTML or text
    location: str | None = None
    work_mode: WorkMode | None = None
    employment_type: str | None = None
    posted_at: date | None = None
    deadline: date | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: Literal["year", "month", "hour"] | None = None
    apply_url: str | None = None
    apply_email: str | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    recruiter_title: str | None = None
    questions: list[str] = Field(default_factory=list)  # application form questions, when the source exposes them
    is_active: bool | None = None
    # Only the mock connector sets "mock"; real sources apply by email (when the posting says so) or manually.
    apply_method: Literal["mock", "email", "manual"] | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class ParsedJob(Strict):
    """Deterministic extraction from a job description. ``parser_version`` keeps results reproducible."""

    parser_version: str
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    experience_min: float | None = None
    experience_max: float | None = None
    seniority: str | None = None
    work_mode: WorkMode | None = None
    employment_type: str | None = None
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None
    salary_text: str | None = None
    education: list[str] = Field(default_factory=list)
    education_mandatory: bool = False
    certifications: list[str] = Field(default_factory=list)
    domain_terms: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)  # e.g. citizenship or clearance requirements
    keywords: list[str] = Field(default_factory=list)
