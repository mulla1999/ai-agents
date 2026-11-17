"""Deterministic job-description parsing: skills (required vs preferred), experience, work mode,
salary, education and restrictions. Results carry ``PARSER_VERSION`` so a stored match can be
reproduced from the stored description.
"""

from __future__ import annotations

import re

from ..domain import ParsedJob, RawJob
from ..skills import extract_domain_terms, extract_skills
from ..text import keywords, normalize

PARSER_VERSION = "jd-2"

_REQUIRED_HEADINGS = re.compile(
    r"^(requirements?|qualifications?|minimum qualifications|basic qualifications|required( skills| qualifications)?|"
    r"must[- ]haves?|what you('ll| will)? (need|bring)|what we('re| are) looking for|who you are|you have|"
    r"skills( required| and experience)?|key skills|technical skills|eligibility|desired profile|candidate profile)\b",
    re.IGNORECASE,
)
_PREFERRED_HEADINGS = re.compile(
    r"^(preferred( qualifications| skills)?|nice[- ]to[- ]haves?|good[- ]to[- ]haves?|bonus( points)?|"
    r"pluses|it('s| is|'d be)? a plus|additional qualifications|desirable)\b",
    re.IGNORECASE,
)
_RESPONSIBILITY_HEADINGS = re.compile(
    r"^(responsibilities|key responsibilities|what you('ll| will) do|the role|role and responsibilities|"
    r"your responsibilities|job description|about the role|in this role)\b",
    re.IGNORECASE,
)
_OTHER_HEADINGS = re.compile(
    r"^(about (us|the company|the team)|benefits|perks|what we offer|why join|compensation|equal opportunity|"
    r"our values|how to apply|location)\b",
    re.IGNORECASE,
)
_PREFERRED_LINE = re.compile(r"\b(nice to have|good to have|preferred|is a plus|a plus|bonus|desirable|ideally)\b", re.I)

_EXPERIENCE = re.compile(
    r"(?P<min>\d{1,2}(?:\.\d)?)\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(?P<max>\d{1,2}(?:\.\d)?)\s*\+?)?\s*"
    r"(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,4}?\s+(?:experience|exp\b)",
    re.IGNORECASE,
)
_EXPERIENCE_ALT = re.compile(
    r"(?:experience|exp)\s*(?:of|:)?\s*(?P<min>\d{1,2})\s*(?:\+|(?:-|–|to)\s*(?P<max>\d{1,2}))?\s*(?:years?|yrs?)",
    re.IGNORECASE,
)

_LPA_RANGE = re.compile(
    r"(?:₹|inr|rs\.?)?\s*(?P<a>\d{1,3}(?:\.\d+)?)\s*(?:-|–|to)\s*(?P<b>\d{1,3}(?:\.\d+)?)\s*(?:lpa|lakhs?(?: per annum)?|l\b)",
    re.IGNORECASE,
)
_LPA_SINGLE = re.compile(r"(?:up to|upto|max(?:imum)?)?\s*(?:₹|inr|rs\.?)?\s*(?P<a>\d{1,3}(?:\.\d+)?)\s*(?:lpa|lakhs per annum)", re.I)
_INR_RANGE = re.compile(
    r"(?:₹|inr|rs\.?)\s*(?P<a>\d{1,3}(?:,\d{2,3})+|\d{6,8})\s*(?:-|–|to)\s*(?:₹|inr|rs\.?)?\s*(?P<b>\d{1,3}(?:,\d{2,3})+|\d{6,8})",
    re.IGNORECASE,
)
_FOREIGN_RANGE = re.compile(
    r"(?P<cur>\$|usd|€|eur|£|gbp)\s*(?P<a>\d{2,3}(?:,\d{3})+|\d{2,3}k)\s*(?:-|–|to)\s*(?:\$|usd|€|eur|£|gbp)?\s*(?P<b>\d{2,3}(?:,\d{3})+|\d{2,3}k)",
    re.IGNORECASE,
)

_DEGREE = re.compile(
    r"(?:(?i:\b(?:b\.?\s?tech|bachelor'?s?|master'?s?|m\.?\s?tech|ph\.?d|mca|bca|b\.?sc|m\.?sc)\b|\bdegree\b(?= in|\s*\())"
    # Short forms only in their exact capitalisation: "be"/"ms" are ordinary words ("will be", "MS Windows").
    r"|\bB\.E\.?|\bBE\b(?=\s*(?:/|in\b|\())|\bM\.S\.(?=\s)|\bMS\b(?=\s+in\b))"
    r"[^.\n]{0,80}"
)
_MANDATORY = re.compile(r"\b(mandatory|must|required|only)\b", re.I)
# Only a mandatory *technical* degree can exclude a non-technical bachelor's.
TECHNICAL_DEGREE = re.compile(r"computer|engineering|information technology|\bIT\b|b\.?\s?tech|\bB\.?E\b|m\.?\s?tech|\bmca\b|technical",
                              re.IGNORECASE)
_EQUIVALENT = re.compile(r"\b(or equivalent|equivalent (practical )?experience|or related experience)\b", re.I)
_CERT = re.compile(r"[^.\n]{0,40}\b(certified|certification|certificate)\b[^.\n]{0,60}", re.I)
_RESTRICTIONS = (
    (re.compile(r"\b(us|u\.s\.) citizens? only\b|\bmust be a (us|u\.s\.) citizen\b", re.I), "US citizenship required"),
    (re.compile(r"\bsecurity clearance\b", re.I), "security clearance required"),
    (re.compile(r"\bno (visa )?sponsorship\b|\bunable to sponsor\b|\bwill not sponsor\b", re.I), "no visa sponsorship"),
    (re.compile(r"\bwomen candidates only\b|\bfemale candidates only\b", re.I), "restricted to a specific group"),
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

SENIORITY_ORDER = ("intern", "junior", "mid", "senior", "lead", "staff", "manager")


def seniority_from_title(title: str) -> str:
    t = title.lower()
    if re.search(r"\bintern(ship)?\b|\btrainee\b", t):
        return "intern"
    if re.search(r"\b(director|head of|vp|vice president|engineering manager)\b", t):
        return "manager"
    # "Member of Technical Staff" is usually a mid-level title, not Staff Engineer.
    if (re.search(r"\bstaff\b", t) and "technical staff" not in t) or re.search(r"\b(principal|distinguished|architect)\b", t):
        return "staff"
    if re.search(r"\b(lead|tech lead)\b", t):
        return "lead"
    if re.search(r"\b(senior|sr\.?|iii|sde ?3|sde-3|l5)\b", t):
        return "senior"
    if re.search(r"\b(junior|jr\.?|associate|graduate|entry|fresher|sde ?1|sde-1|i)\b", t):
        return "junior"
    return "mid"


def work_mode_from_text(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\bhybrid\b", t):
        return "hybrid"
    if re.search(r"\b(fully remote|100% remote|remote[- ]first|work from home|wfh|remote)\b", t) and not re.search(
        r"\bnot remote\b|\bno remote\b", t
    ):
        return "remote"
    if re.search(r"\b(on[- ]?site|in[- ]office|work from office|wfo)\b", t):
        return "onsite"
    return None


def _sections(text: str) -> list[tuple[str, str]]:
    """Split into (kind, line) where kind is required | preferred | responsibility | other | general."""
    kind = "general"
    out: list[tuple[str, str]] = []
    for line in text.split("\n"):
        stripped = line.strip().lstrip("•*-– ").strip()
        if not stripped:
            continue
        head = stripped.rstrip(":").strip()
        if len(head) <= 60 and not head.endswith("."):
            if _PREFERRED_HEADINGS.match(head):
                kind = "preferred"
                continue
            if _REQUIRED_HEADINGS.match(head):
                kind = "required"
                continue
            if _RESPONSIBILITY_HEADINGS.match(head):
                kind = "responsibility"
                continue
            if _OTHER_HEADINGS.match(head):
                kind = "other"
                continue
        out.append((kind, stripped))
    return out


def _lpa(value: str) -> float:
    return float(value.replace(",", "")) / 100000


def parse_salary(text: str, raw: RawJob | None, fx: dict[str, float]) -> tuple[float | None, float | None, str | None]:
    if raw and raw.salary_min is not None and raw.salary_currency:
        cur = raw.salary_currency.upper()
        factor = {"year": 1, "month": 12, "hour": 2000}.get(raw.salary_period or "year", 1)
        rate = 1.0 if cur == "INR" else fx.get(cur)
        lo, hi = raw.salary_min * factor, (raw.salary_max or raw.salary_min) * factor
        label = f"{cur} {lo:,.0f}–{hi:,.0f} per year"
        if rate is None:
            return None, None, label
        return round(lo * rate / 100000, 1), round(hi * rate / 100000, 1), label
    if m := _LPA_RANGE.search(text):
        return float(m.group("a")), float(m.group("b")), m.group(0).strip()
    if m := _INR_RANGE.search(text):
        return round(_lpa(m.group("a")), 1), round(_lpa(m.group("b")), 1), m.group(0).strip()
    if m := _LPA_SINGLE.search(text):
        value = float(m.group("a"))
        upper = "up to" in m.group(0).lower() or "upto" in m.group(0).lower() or "max" in m.group(0).lower()
        return (None if upper else value), value, m.group(0).strip()
    if m := _FOREIGN_RANGE.search(text):
        cur = {"$": "USD", "€": "EUR", "£": "GBP"}.get(m.group("cur"), m.group("cur").upper())

        def amount(v: str) -> float:
            v = v.lower().replace(",", "")
            return float(v[:-1]) * 1000 if v.endswith("k") else float(v)

        lo, hi = amount(m.group("a")), amount(m.group("b"))
        rate = fx.get(cur)
        if rate is None:
            return None, None, m.group(0).strip()
        return round(lo * rate / 100000, 1), round(hi * rate / 100000, 1), m.group(0).strip()
    return None, None, None


def parse_job(raw: RawJob, text: str, fx_rates: dict[str, float] | None = None) -> ParsedJob:
    sections = _sections(text)
    has_required_section = any(k == "required" for k, _ in sections)
    required: list[str] = []
    preferred: list[str] = []
    responsibilities: list[str] = []
    for kind, line in sections:
        if kind == "other":
            continue
        found = extract_skills(line)
        if kind == "responsibility":
            responsibilities.append(line)
        if kind == "preferred" or _PREFERRED_LINE.search(line):
            preferred.extend(found)
        elif kind == "required" or not has_required_section:
            required.extend(found)
        else:
            # Mentioned in the responsibilities or intro of a JD that has an explicit requirements list.
            preferred.extend(found)
    required = list(dict.fromkeys(required))
    preferred = [s for s in dict.fromkeys(preferred) if s not in required]
    # Title skills ("Java Developer", "React Engineer") are always required.
    for skill in extract_skills(raw.title):
        if skill not in required:
            required.insert(0, skill)
            if skill in preferred:
                preferred.remove(skill)

    # The employer's own product is not a requirement ("MongoDB" in every MongoDB posting).
    company = set(normalize(raw.company).split())
    if company:
        own = {s for s in required + preferred
               if (words := set(normalize(s).split())) and (words <= company or company <= words)}
        required = [s for s in required if s not in own]
        preferred = [s for s in preferred if s not in own]

    exp_min = exp_max = None
    relevant = "\n".join(line for kind, line in sections if kind != "other")
    for pattern in (_EXPERIENCE, _EXPERIENCE_ALT):
        if m := pattern.search(relevant):
            exp_min = float(m.group("min"))
            exp_max = float(m.group("max")) if m.group("max") else None
            if exp_max is not None and exp_max < exp_min:
                exp_min, exp_max = exp_max, exp_min
            break

    education: list[str] = []
    mandatory = False
    for m in _DEGREE.finditer(relevant):
        # Judge the whole line the degree appears on ("BE/B.Tech required"), not the matched fragment.
        start = relevant.rfind("\n", 0, m.start()) + 1
        end = relevant.find("\n", m.end())
        line = relevant[start:end if end != -1 else None].strip()
        education.append(line[:200])
        if _MANDATORY.search(line) and not _EQUIVALENT.search(line) and TECHNICAL_DEGREE.search(line):
            mandatory = True
    certifications = [m.group(0).strip() for m in _CERT.finditer(relevant)][:5]

    smin, smax, stext = parse_salary(text, raw, fx_rates or {})
    restrictions = [label for pattern, label in _RESTRICTIONS if pattern.search(text)]
    return ParsedJob(
        parser_version=PARSER_VERSION,
        required_skills=required,
        preferred_skills=preferred,
        responsibilities=responsibilities[:30],
        experience_min=exp_min,
        experience_max=exp_max,
        seniority=seniority_from_title(raw.title),
        work_mode=raw.work_mode or work_mode_from_text(f"{raw.location or ''}\n{raw.title}\n{text[:3000]}"),
        employment_type=raw.employment_type,
        salary_min_lpa=smin,
        salary_max_lpa=smax,
        salary_text=stext,
        education=list(dict.fromkeys(education))[:5],
        education_mandatory=mandatory,
        certifications=certifications,
        domain_terms=extract_domain_terms(text),
        emails=list(dict.fromkeys(e.lower() for e in _EMAIL.findall(text)))[:5],
        restrictions=restrictions,
        keywords=sorted(keywords(" ".join(responsibilities)))[:80],
    )
