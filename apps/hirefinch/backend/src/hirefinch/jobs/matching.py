"""Explainable 0–100 job match.

Each criterion returns a sub-score in [0, 1] or ``None`` when the posting does not give enough
information. The total is the weighted mean of the *available* criteria, so missing information
lowers confidence, not the score, and is reported separately from a confirmed mismatch.
Disqualifiers (a hard requirement you demonstrably miss) override the number entirely.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ..candidate import CandidateProfile
from ..domain import ParsedJob, Preferences
from ..skills import ROLE_FAMILIES, category_of, extract_skills
from ..text import keywords, normalize, normalize_company
from .parser import SENIORITY_ORDER

SCORER_VERSION = "m-1"

_TITLE_SYNONYMS = {
    "developer": "engineer",
    "programmer": "engineer",
    "sde": "software engineer",
    "swe": "software engineer",
    "fullstack": "full stack",
    "full-stack": "full stack",
    "back-end": "backend",
    "back end": "backend",
    "front-end": "frontend",
    "front end": "frontend",
    "genai": "generative ai",
    "gen ai": "generative ai",
    "ml": "machine learning",
    "llm": "ai",
}
_TITLE_FILLER = frozenset({"senior", "sr", "junior", "jr", "lead", "staff", "principal", "i", "ii", "iii", "iv", "the", "and",
                           "of", "associate", "level"})


@dataclass
class Criterion:
    key: str
    label: str
    weight: float
    score: float | None  # None = not enough information
    detail: str

    @property
    def available(self) -> bool:
        return self.score is not None


@dataclass
class MatchResult:
    score: float
    band: str
    confidence: str
    recommended: bool
    criteria: list[Criterion]
    disqualifiers: list[str]
    explanation: dict[str, Any] = field(default_factory=dict)

    def breakdown(self) -> dict[str, Any]:
        return {c.key: asdict(c) for c in self.criteria}


_MISSING_FIELDS = {"skills", "experience requirement", "domain signals", "location / work mode", "compensation"}

def _title_tokens(title: str) -> set[str]:
    t = normalize(title)
    for a, b in _TITLE_SYNONYMS.items():
        t = re.sub(rf"\b{re.escape(a)}\b", b, t)
    return {w for w in t.split() if w not in _TITLE_FILLER}


def title_similarity(title: str, targets: list[str]) -> tuple[float, str | None]:
    tokens = _title_tokens(title)
    best, best_target = 0.0, None
    for target in targets:
        other = _title_tokens(target)
        if not tokens or not other:
            continue
        score = len(tokens & other) / len(tokens | other)
        if other <= tokens:  # "Software Engineer" inside "Software Engineer, Platform"
            score = max(score, 0.85)
        if score > best:
            best, best_target = score, target
    return best, best_target


_ENGINEERING_TITLE = re.compile(r"\b(engineer|engineering|developer|sde|swe|programmer|architect|devops|sre|technical staff|mts)\b", re.I)
_NON_ENGINEERING_TITLE = re.compile(
    r"\b(sales|account (executive|manager|development)|representative|writer|recruit\w*|marketing|finance|legal|counsel|"
    r"real estate|compensation|people (systems|partner|operations)|customer (success|experience)|success manager|"
    r"partner|program manager|product manag\w*|designer|analyst|consultant|director|vp|head of)\b",
    re.I,
)


def is_non_engineering(title: str) -> bool:
    """Sales, writing, analytics, programme and people roles, even with 'Engineer' in the name
    ('Sales Compensation Engineer', 'Customer Experience Engineer')."""
    return bool(_NON_ENGINEERING_TITLE.search(title)) or not _ENGINEERING_TITLE.search(title)


def candidate_level(years: float) -> str:
    if years < 1:
        return "intern"
    if years < 2:
        return "junior"
    if years < 5:
        return "mid"
    if years < 8:
        return "senior"
    return "staff"


def role_family(title: str, skills: list[str]) -> str:
    t = normalize(title)
    for family, spec in ROLE_FAMILIES.items():
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in spec["title_words"]):  # type: ignore[union-attr]
            if family == "java_backend" and sum(category_of(s) == "ai" for s in skills) >= 4:
                return "ai_engineering"
            return family
    ai = sum(category_of(s) == "ai" for s in skills)
    fe = sum(category_of(s) == "frontend" for s in skills)
    if ai >= 3:
        return "ai_engineering"
    if fe >= 2:
        return "full_stack"
    return "java_backend"


def _location_ok(location: str | None, preferred: list[str]) -> bool | None:
    if not location:
        return None
    loc = normalize(location)
    aliases = {"bengaluru": "bangalore", "bangalore": "bengaluru", "mumbai": "bombay", "gurugram": "gurgaon"}
    for pref in preferred:
        p = normalize(pref)
        if p and (p in loc or (aliases.get(p) and aliases[p] in loc)):
            return True
    return False


def evaluate(
    *,
    title: str,
    company: str,
    location: str | None,
    parsed: ParsedJob,
    description: str,
    candidate: CandidateProfile,
    prefs: Preferences,
    flags: dict[str, Any] | None = None,
    willing_to_relocate: bool | None = None,
) -> MatchResult:
    w = prefs.weights
    flags = flags or {}
    disqualifiers: list[str] = []
    unknowns: list[str] = []

    # --- technical skills
    req, pref = parsed.required_skills, parsed.preferred_skills
    req_hit = [s for s in req if candidate.has(s)]
    pref_hit = [s for s in pref if candidate.has(s)]
    req_miss = [s for s in req if not candidate.has(s)]
    pref_miss = [s for s in pref if not candidate.has(s)]
    if req or pref:
        req_cov = len(req_hit) / len(req) if req else None
        pref_cov = len(pref_hit) / len(pref) if pref else None
        if req_cov is not None and pref_cov is not None:
            tech = 0.75 * req_cov + 0.25 * pref_cov
        else:
            tech = req_cov if req_cov is not None else pref_cov
        tech_detail = f"{len(req_hit)}/{len(req)} required and {len(pref_hit)}/{len(pref)} preferred skills"
    else:
        tech, tech_detail = None, "no recognisable skills in the description"
        unknowns.append("skills")

    # --- experience & responsibilities
    years = candidate.years_experience
    exp_parts: list[float] = []
    exp_detail: list[str] = []
    if parsed.experience_min is not None:
        need = parsed.experience_min
        if years >= need:
            fit = 1.0
            if parsed.experience_max is not None and years > parsed.experience_max + 3:
                fit = 0.7
                exp_detail.append(f"you have {years:g}y, above the {parsed.experience_max:g}y upper bound")
            else:
                exp_detail.append(f"needs {need:g}+ years; you have {years:g}")
        else:
            gap = need - years
            fit = max(0.0, 1 - gap / 3)
            exp_detail.append(f"needs {need:g}+ years; you have {years:g} ({gap:.1f}y short)")
            if gap > prefs.max_experience_gap_years:
                disqualifiers.append(f"requires {need:g}+ years of experience; you have {years:g}")
        exp_parts.append(fit)
    else:
        unknowns.append("experience requirement")
    resume = candidate.resume
    if parsed.responsibilities and resume is not None:
        bullet_kw = [keywords(b.text) for b in resume.all_bullets()]
        covered = 0
        for line in parsed.responsibilities:
            kw = keywords(line)
            if kw and any(len(kw & b) >= 2 for b in bullet_kw):
                covered += 1
        resp = covered / len(parsed.responsibilities)
        exp_parts.append(min(1.0, resp * 1.25))
        exp_detail.append(f"{covered}/{len(parsed.responsibilities)} responsibilities resemble your past work")
    experience = sum(exp_parts) / len(exp_parts) if exp_parts else None

    # --- role & seniority
    sim, closest = title_similarity(title, prefs.target_roles)
    non_engineering = is_non_engineering(title)
    if tech is not None and tech >= 0.6 and not non_engineering:
        sim = max(sim, 0.5)  # a different title with a strong skill match still deserves a look
    level = parsed.seniority or "mid"
    mine = candidate_level(years)
    diff = SENIORITY_ORDER.index(level) - SENIORITY_ORDER.index(mine) if level in SENIORITY_ORDER else 0
    seniority_fit = {0: 1.0, 1: 0.85, 2: 0.4}.get(diff, 0.6 if diff < 0 else 0.15)
    if level == "manager":
        seniority_fit = min(seniority_fit, 0.2)
    role = 0.6 * sim + 0.4 * seniority_fit
    role_detail = f"title is closest to '{closest or '-'}' ({sim:.0%}); level {level} vs your {mine}"

    # --- AI / cloud / architecture / domain
    jd_domain = [s for s in req + pref if category_of(s) in ("ai", "cloud")] + parsed.domain_terms
    if jd_domain:
        corpus = normalize(resume.full_text()) if resume else ""
        hit = [t for t in jd_domain if candidate.has(t) or normalize(t) in corpus]
        domain = len(hit) / len(jd_domain)
        domain_detail = f"{len(hit)}/{len(jd_domain)} AI, cloud and domain signals in your background"
    else:
        domain, domain_detail = None, "no AI, cloud or domain signals in the description"
        unknowns.append("domain signals")

    # --- location & work mode
    mode = parsed.work_mode
    loc_ok = _location_ok(location, prefs.preferred_locations)
    if mode is None and loc_ok is None:
        loc_score, loc_detail = None, "location and work mode not stated"
        unknowns.append("location / work mode")
    else:
        mode_ok = mode is None or mode in prefs.work_modes
        if mode == "remote":
            loc_score = 1.0 if mode_ok else 0.0
        elif loc_ok is False:
            loc_score = 0.2 if mode_ok else 0.0
            if mode == "onsite" and prefs.onsite_only_in_preferred_locations and not willing_to_relocate:
                disqualifiers.append(f"on-site in {location}, outside your preferred locations")
        else:
            loc_score = 1.0 if mode_ok else 0.0
        if mode is not None and not mode_ok:
            disqualifiers.append(f"work mode '{mode}' is not one you accept")
        loc_detail = f"{mode or 'mode not stated'} · {location or 'location not stated'}"

    # --- compensation
    floor = prefs.min_compensation_lpa
    if parsed.salary_max_lpa is not None and floor is not None:
        top = parsed.salary_max_lpa
        target_low = prefs.target_compensation_lpa[0] if prefs.target_compensation_lpa else floor
        if top >= target_low:
            comp = 1.0
        elif top >= floor:
            comp = 0.7
        else:
            comp = max(0.0, top / floor - 0.3)
            disqualifiers.append(f"published pay tops out at {top:g} LPA, below your minimum of {floor:g} LPA")
        comp_detail = f"published {parsed.salary_text}"
    else:
        comp, comp_detail = None, (f"pay published as {parsed.salary_text} (no exchange rate set)" if parsed.salary_text
                                   else "pay not published")
        unknowns.append("compensation")

    # --- hard requirements outside the score
    if parsed.education_mandatory and not candidate.has_cs_degree:
        disqualifiers.append("a specific degree is stated as mandatory and your degree may not qualify: "
                             + "; ".join(parsed.education[:2]))
    for restriction in parsed.restrictions:
        if restriction != "no visa sponsorship":
            disqualifiers.append(restriction)
    if normalize_company(company) in {normalize_company(c) for c in prefs.excluded_companies}:
        disqualifiers.append("company is on your excluded list")
    lowered = description.lower()
    for word in prefs.excluded_keywords:
        if word.strip() and re.search(rf"\b{re.escape(word.lower())}\b", lowered):
            disqualifiers.append(f"contains excluded keyword '{word}'")

    criteria = [
        Criterion("technical", "Technical skill match", w.technical, tech, tech_detail),
        Criterion("experience", "Relevant experience and responsibilities", w.experience, experience,
                  "; ".join(exp_detail) or "experience requirement not stated"),
        Criterion("role", "Role and seniority alignment", w.role, role, role_detail),
        Criterion("domain", "AI, cloud, architecture or domain relevance", w.domain, domain, domain_detail),
        Criterion("location", "Location and work mode", w.location, loc_score, loc_detail),
        Criterion("compensation", "Compensation", w.compensation, comp, comp_detail),
    ]
    available = [c for c in criteria if c.available and c.weight > 0]
    total_weight = sum(c.weight for c in criteria if c.weight > 0)
    avail_weight = sum(c.weight for c in available)
    score = round(100 * sum(c.weight * c.score for c in available) / avail_weight, 1) if avail_weight else 0.0  # type: ignore[operator]

    coverage = avail_weight / total_weight if total_weight else 0
    if coverage >= 0.85 and len(req) >= 3:
        confidence = "high"
    elif coverage >= 0.6 and len(req) + len(pref) >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    t = prefs.thresholds
    if disqualifiers:
        band = "disqualified"
    elif score >= t.high:
        band = "high"
    elif score >= t.good:
        band = "good"
    elif score >= t.review:
        band = "review"
    else:
        band = "low"
    if confidence == "low" and band in ("high", "good"):
        # A near-perfect score built from two or three facts is not a strong match: review it yourself.
        band = "review"
        unknowns.append("too little detail in the posting for a confident score")
    # Titles outside software engineering, or two+ levels above you, are shown for review but never
    # shortlisted automatically. Not a rejection: you can still shortlist them yourself.
    if band in ("high", "good") and non_engineering:
        band = "review"
        unknowns.append("the title suggests a role outside software engineering")
    if band in ("high", "good") and diff >= 2:
        band = "review"
        unknowns.append(f"the role is {level} level; your experience fits {mine}")
    # The number must mean the same thing everywhere (lists, alerts, the automatic-apply threshold), so a
    # role that is clearly not yours cannot show 85+, and a score built from a one-line snippet stays
    # below the automatic threshold until the full description is known.
    uncapped, caps = score, []
    if non_engineering:
        caps.append((60.0, "the title is outside software engineering"))
    if diff >= 2 or level == "manager":
        caps.append((60.0, f"the role is {level} level; your experience fits {mine}"))
    if diff <= -2:
        caps.append((60.0, f"the role is {level} level, well below your {mine} experience"))
    if confidence == "low":
        caps.append((80.0, "too little detail in the posting to score above 80"))
    for limit, reason in caps:
        if score > limit:
            score = limit
    if score < uncapped and band in ("high", "good"):
        band = "review"
    blocked = flags.get("suspicious") or flags.get("prompt_injection")
    recommended = band in ("high", "good") and not blocked

    family = role_family(title, req + pref)
    explanation = _explain(
        candidate=candidate, parsed=parsed, req_hit=req_hit, pref_hit=pref_hit, req_miss=req_miss, pref_miss=pref_miss,
        band=band, recommended=recommended, confidence=confidence, unknowns=unknowns, disqualifiers=disqualifiers,
        flags=flags, criteria=criteria, family=family,
    )
    if score < uncapped:
        explanation["uncapped_score"] = uncapped
        explanation["score_caps"] = [reason for limit, reason in caps if uncapped > limit]
    return MatchResult(score, band, confidence, recommended, criteria, disqualifiers, explanation)


def _relevant_projects(candidate: CandidateProfile, skills: list[str]) -> list[dict[str, Any]]:
    resume = candidate.resume
    if resume is None:
        return []
    wanted = set(skills)
    ranked = []
    for project in resume.projects:
        text = " ".join([project.name, *project.technologies, *(b.text for b in project.bullets)])
        overlap = [s for s in extract_skills(text) if s in wanted]
        if overlap:
            ranked.append({"project": project.name, "matching_skills": overlap})
    ranked.sort(key=lambda p: -len(p["matching_skills"]))
    return ranked[:3]


def _explain(*, candidate: CandidateProfile, parsed: ParsedJob, req_hit: list[str], pref_hit: list[str],
             req_miss: list[str], pref_miss: list[str], band: str, recommended: bool, confidence: str,
             unknowns: list[str], disqualifiers: list[str], flags: dict[str, Any], criteria: list[Criterion],
             family: str) -> dict[str, Any]:
    strongest = []
    for skill in (req_hit + pref_hit)[:8]:
        evidence = candidate.skills.get(skill, [])
        places = sorted({e.where.split(":")[0] for e in evidence})
        strongest.append({"skill": skill, "evidence": places, "mentions": len(evidence)})
    strongest.sort(key=lambda s: -s["mentions"])
    why = [f"{c.label}: {c.detail}" for c in criteria if c.available and (c.score or 0) >= 0.7]
    gaps = [f"Required skill not evidenced in your resume: {s}" for s in req_miss]
    gaps += [f"Preferred skill not evidenced: {s}" for s in pref_miss[:6]]
    if parsed.certifications:
        have = " ".join(candidate.certifications).lower()
        for cert in parsed.certifications:
            if not any(word in have for word in normalize(cert).split() if len(word) > 4):
                gaps.append(f"Mentions a certification you have not listed: {cert}")
    if band == "disqualified":
        recommendation = "Not recommended: " + "; ".join(disqualifiers)
    elif flags.get("prompt_injection"):
        recommendation = "Review manually: the posting contains text that tries to instruct an AI"
    elif flags.get("suspicious"):
        recommendation = "Review manually: " + "; ".join(flags.get("suspicious_reasons", []))
    elif recommended:
        recommendation = "Apply: strong fit" if band == "high" else "Apply: good fit"
    elif band == "review":
        recommendation = "Review manually: partial fit"
    else:
        recommendation = "Skip: weak fit"
    # Missing fields read "skills not stated in the posting"; the full-sentence notes stay as written.
    uncertainty = [f"{u} not stated in the posting" if u in _MISSING_FIELDS else u for u in unknowns]
    if confidence == "low" and not parsed.required_skills:
        uncertainty.append("few concrete requirements could be extracted")
    return {
        "why_matches": why,
        "strongest_skills": strongest,
        "relevant_projects": _relevant_projects(candidate, req_hit + pref_hit),
        "missing_required": req_miss,
        "missing_preferred": pref_miss,
        "resume_gaps": gaps,
        "recommendation": recommendation,
        "interview_emphasis": [s["skill"] for s in strongest[:4]]
        + [p["project"] for p in _relevant_projects(candidate, req_hit + pref_hit)[:2]],
        "confidence_reasons": uncertainty or ["all scoring criteria had information"],
        "unknown_criteria": unknowns,
        "role_family": family,
        "years_used": candidate.years_experience,
    }
