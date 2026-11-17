"""Application questions: classify each one and answer it only from facts on record.

Sources, in order: your confirmed answers, your profile (including Self-identification and Common
questions), and what your resume states (name, contact, employers, education, experience). Nothing is
inferred: gender, ethnicity, disability and similar questions are answered only with what you wrote
in Profile, and declarations only when you allowed it. Anything not on record waits for you.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..candidate import CandidateProfile
from ..domain import Profile, plausible_lpa
from ..skills import extract_skills
from ..text import normalize

_RULES: tuple[tuple[str, str], ...] = (
    ("captcha", r"captcha|i am not a robot|verify you are human"),
    ("gender", r"\bgender\b|\bsex\b(?! offender)"),
    ("pronouns", r"\bpronoun"),
    ("ethnicity", r"\b(race|ethnicity|ethnic)\b"),
    ("disability", r"\bdisab"),
    ("veteran", r"\bveteran"),
    ("date_of_birth", r"\bdate of birth\b|\bbirth ?date\b|\bdob\b"),
    ("demographic", r"\b(religion|caste|category \(sc|marital|age\b|sexual orientation)"),
    ("nationality", r"\b(nationality|citizenship)\b"),  # answered only from what you wrote in Profile
    ("criminal_record", r"\b(convicted|criminal (record|offen[cs]e|history))\b"),
    ("background_check", r"\bbackground (check|verification|screening)\b"),
    ("legal_declaration", r"\b(i (hereby )?(certify|declare|confirm|agree|acknowledge|consent)|terms and conditions|"
                          r"privacy (policy|notice)|consent)\b"),
    ("previous_employer", r"\b(previously|ever|before) (worked|been employed|consulted)|\bformer employee\b|"
                          r"\b(worked|consulted) (at|for) .{2,60} (before|previously)\b"),
    ("based_in", r"\bare you (currently )?(based|located|living|residing) (in|out of|at|near)\b"),
    ("country_of_residence", r"\bcountry of residence\b|\bcurrent country\b|\bwhich country (are|do) you (live|reside|based)"),
    ("managed_team", r"\b(managing|managed|lead(ing)?|led) (a )?(team|people)\b|\bpeople management\b"),
    ("education", r"\bhighest (level of )?(education|qualification|degree)\b|\beducation(al)? (level|qualification)\b"),
    ("how_heard", r"\bhow did you (hear|find|learn|come across)\b"),
    ("onsite", r"\b(work|working) (from|in) (the )?office\b|\bon-?site\b.*\b(ok|okay|comfortable|willing|able)\b"),
    ("current_salary", r"\b(current|present|last drawn) (ctc|salary|compensation|package)\b"),
    ("expected_salary", r"\b(expected|desired|expectation)\b.*\b(ctc|salary|compensation|pay|package)\b|"
                        r"\b(salary|ctc|compensation) expectations?\b"),
    ("sponsorship", r"\bsponsor(ship)?\b|\bvisa\b"),
    ("work_authorization", r"\b(authori[sz]ed|eligible|legally (able|permitted)|right) to work\b|work (permit|authori[sz]ation)"),
    ("relocation", r"\brelocat"),
    ("notice_period", r"\bnotice period\b|\bhow soon can you (join|start)\b|\bearliest (start|joining) date\b"),
    ("experience_years", r"\b(how many )?years of\b.*\bexperience\b|\btotal experience\b|\byears of experience\b"),
    ("email", r"\be-?mail\b"),
    ("phone", r"\b(phone|mobile|contact number)\b"),
    ("linkedin", r"\blinkedin\b"),
    ("name", r"\b(full name|first name|last name|your name|^name$)\b"),
    ("location", r"\b(current (city|location)|where are you (located|based)|^location$|city of residence)\b"),
    ("free_text", r"\b(why|describe|tell us|explain|what makes|cover letter|motivation|share an example)\b"),
)
_RULES_RE = [(category, re.compile(pattern, re.IGNORECASE)) for category, pattern in _RULES]

NEVER_AUTOMATIC = frozenset({"captcha", "demographic"})
SENSITIVE = frozenset({"gender", "pronouns", "ethnicity", "disability", "veteran", "date_of_birth", "demographic", "nationality",
                       "criminal_record", "current_salary", "expected_salary", "phone"})
_CITY_ALIASES = {"bangalore": "bengaluru", "bombay": "mumbai", "gurgaon": "gurugram", "madras": "chennai", "calcutta": "kolkata"}


@dataclass
class PreparedAnswer:
    question: str
    category: str
    answer: str | None
    source: str  # profile | resume | user | none
    sensitive: bool
    needs_user: bool
    reason: str | None = None


def classify(question: str) -> str:
    for category, pattern in _RULES_RE:
        if pattern.search(question):
            return category
    return "unknown"


def _custom(profile: Profile, question: str) -> str | None:
    q = normalize(question)
    for key, value in profile.custom_answers.items():
        if normalize(key) and normalize(key) in q and value.strip():
            return value.strip()
    return None


def _yes(value: bool | None) -> str | None:
    return None if value is None else ("Yes" if value else "No")


def _city(text: str) -> str:
    t = normalize(text)
    return _CITY_ALIASES.get(t, t)


def prepare_answer(question: str, profile: Profile, candidate: CandidateProfile, company: str | None = None) -> PreparedAnswer:
    category = classify(question)
    sensitive = category in SENSITIVE
    contact = candidate.resume.contact if candidate.resume else None

    def known(value: object, source: str = "profile") -> PreparedAnswer:
        return PreparedAnswer(question, category, str(value), source, sensitive, False)

    def ask(reason: str) -> PreparedAnswer:
        return PreparedAnswer(question, category, None, "none", sensitive, True, reason)

    if category in NEVER_AUTOMATIC:
        return ask({"captcha": "the form needs a CAPTCHA; only you can complete it",
                    "demographic": "sensitive personal question; answer it yourself or decline to answer"}[category])
    if (custom := _custom(profile, question)) is not None:
        return known(custom, "user")
    if category == "nationality":
        return ask("add it under Profile → your answers to other recurring questions (e.g. 'nationality = Indian')")
    me, common = profile.self_identification, profile.common_answers
    if category in ("gender", "pronouns", "ethnicity", "disability", "veteran", "date_of_birth"):
        value = getattr(me, category)
        return known(value, "user") if value else ask(f"set {category.replace('_', ' ')} in Profile → Self-identification, "
                                                      "or answer it yourself")
    if category == "criminal_record":
        return known(_yes(common.criminal_record), "user") if common.criminal_record is not None else ask(
            "answer it in Profile → Common questions, or on the form")
    if category == "background_check":
        return known(_yes(common.background_check_consent), "user") if common.background_check_consent is not None else ask(
            "set background-check consent in Profile → Common questions")
    if category == "legal_declaration":
        return known("Yes", "user") if common.accept_declarations else ask(
            "a declaration or consent: allow it in Profile → Common questions, or confirm it yourself")
    if category == "previous_employer":
        if not company:
            return ask("which employer is meant is unclear")
        mine = {normalize(e.company) for e in (candidate.resume.experience if candidate.resume else [])}
        from ..text import normalize_company

        here = normalize_company(company)
        worked = any(here and (here in normalize_company(m) or normalize_company(m) in here) for m in mine)
        return known("Yes" if worked else "No", "resume")
    if category == "based_in":
        where = re.split(r"\b(?:in|out of|at|near)\b", question, maxsplit=1)[-1]
        target = _city(re.sub(r"[?*✱]", "", where).split(",")[0])
        home = profile.location or (contact.location if contact else None)
        if not home or not target:
            return ask("your location is not set in Profile")
        return known("Yes" if target and target in _city(home.split(",")[0]) or target in normalize(home) else "No", "profile")
    if category == "country_of_residence":
        return known(common.country_of_residence) if common.country_of_residence else ask("set your country in Profile → Common questions")
    if category == "managed_team":
        return known(_yes(common.managed_team)) if common.managed_team is not None else ask(
            "set whether you have managed a team in Profile → Common questions")
    if category == "education":
        value = common.highest_education or (candidate.resume.education[0] if candidate.resume and candidate.resume.education else None)
        return known(value, "resume") if value else ask("no education on record")
    if category == "how_heard":
        return known(common.how_did_you_hear) if common.how_did_you_hear else ask("set how you usually find jobs in Profile")
    if category == "onsite":
        return known(_yes(common.willing_onsite)) if common.willing_onsite is not None else ask(
            "set whether you can work on-site in Profile → Common questions")
    if category == "name":
        return known(profile.full_name or candidate.name, "resume")
    if category == "email":
        value = profile.contact_email or (contact.email if contact else None)
        return known(value, "resume") if value else ask("no contact email on record")
    if category == "phone":
        value = profile.phone or (contact.phone if contact else None)
        return known(value, "resume") if value else ask("no phone number on record")
    if category == "linkedin":
        value = profile.linkedin_url or next((link for link in (contact.links if contact else []) if "linkedin" in link.lower()), None)
        return known(value, "resume") if value else ask("no LinkedIn URL on record")
    if category == "location":
        value = profile.location or (contact.location if contact else None)
        return known(value, "resume") if value else ask("no location on record")
    if category == "experience_years":
        if extract_skills(question):
            return ask("asks for years with a specific technology; your resume does not state that separately")
        return known(f"{candidate.years_experience:g}", "resume")
    if category == "notice_period":
        return known(f"{profile.notice_period_days} days") if profile.notice_period_days is not None else ask(
            "notice period not set in your profile")
    if category in ("expected_salary", "current_salary"):
        raw = profile.expected_ctc_lpa if category == "expected_salary" else profile.current_ctc_lpa
        label = "salary expectation" if category == "expected_salary" else "current salary"
        if raw is None:
            return ask(f"{label} not set in your profile")
        if (value := plausible_lpa(raw)) is None:  # e.g. rupees typed into the LPA field
            return ask(f"{label} in your profile ({raw:g}) is not a valid LPA figure; fix it in Profile")
        return known(f"{value:g} LPA")
    if category == "sponsorship":
        if profile.requires_sponsorship is None:
            return ask("sponsorship need not set in your profile")
        return known("Yes" if profile.requires_sponsorship else "No")
    if category == "work_authorization":
        countries = [c.lower() for c in profile.authorized_to_work_in]
        mentioned = [c for c in countries if c in question.lower()]
        if mentioned:
            return known("Yes")
        return ask("cannot tell which country this asks about, or your work authorisation is not set")
    if category == "relocation":
        if profile.willing_to_relocate is None:
            return ask("relocation preference not set in your profile")
        return known("Yes" if profile.willing_to_relocate else "No")
    if category == "free_text":
        return ask("needs a written answer in your own words")
    return ask("unrecognised question")
