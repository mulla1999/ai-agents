"""Checks on what you type to the assistant, before any model or tool sees it.

The assistant works only on your own account through the same services as the rest of the app, so it
cannot reach another user's data or an admin function even if asked. These checks add clear refusals
for requests it must not attempt, and keep input to a sane size:

* requests for other people's data, admin powers, secrets, the system prompt or the server;
* attempts to bypass a site's rules: scraping boards that forbid it, solving CAPTCHAs, fake
  accounts, mass-applying;
* fabricating resume content or application answers;
* abuse and content that has nothing to do with a job search (answered with a short redirect).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_CHARS = 2000

_RULES: tuple[tuple[str, str], ...] = (
    (r"\b(other|another|all|every)\s+(users?|accounts?|candidates?|people)('s)?\b.*\b(data|resumes?|jobs?|emails?|details|applications?|profiles?)\b"
     r"|\b(show|list|give|export|dump)\b.*\b(all|every|other)\s+(users?|accounts?)\b",
     "I can only work with your own account. Other people's data is never available to me."),
    (r"\b(make|set|give|grant|promote)\b.*\b(me|my account|user)\b.*\b(admin|superadmin|administrator|root)\b"
     r"|\b(admin|superadmin)\s+(access|rights|role|panel|password)\b|\bdisable\s+(2fa|two.factor|rate.?limit|audit|logging)\b",
     "I can't change roles or security settings. An administrator manages accounts in Administration."),
    (r"\b(api[ _-]?keys?|secret[ _-]?keys?|passwords?|tokens?|credentials|encryption key|smtp password|\.env)\b.*\b(show|reveal|print|tell|give|send|what is|display)\b"
     r"|\b(show|reveal|print|tell|give|send|display)\b.*\b(api[ _-]?keys?|secret[ _-]?keys?|passwords?|tokens?|credentials|encryption key|\.env)\b",
     "Saved keys and passwords are write-only: nobody, including me, can read them back. You can replace them in Integrations."),
    (r"\b(system|developer|hidden)\s+(prompt|instructions?|message)\b|\bignore (all |any )?(the )?(previous|prior|above|your) (instructions|rules)\b"
     r"|\byou are no longer\b|\bjailbreak\b|\bDAN mode\b",
     "I'll stick to helping with your job search. What would you like to do: find jobs, check an application, or apply?"),
    (r"\b(run|execute|eval)\b.*\b(command|shell|script|code|sql|query)\b|\b(rm -rf|drop table|delete from|select \* from)\b"
     r"|\b(server|database|filesystem|file system)\b.*\b(access|read|files?|dump)\b",
     "I can't run commands or touch the server. I only act through the app's job-search features."),
    (r"\b(scrape|crawl|bot|automate|bypass)\b.*\b(linkedin|naukri|indeed|glassdoor|hirist|foundit|monster)\b"
     r"|\b(bypass|solve|crack|skip)\b.*\bcaptcha\b|\bfake (account|profile|identity)\b|\b(create|make)\b.*\b(many|multiple|bulk) accounts\b",
     "I can't scrape or automate sites that forbid it, or get around CAPTCHAs. For LinkedIn, Naukri, Indeed and Hirist, "
     "set up job-alert emails (the agent reads them) or paste a posting's link or text and I'll import it."),
    (r"\bapply\b.*\b(to )?(all|every|each|hundreds|100\+?)\b.*\bjobs?\b|\bmass[- ]apply\b|\bspam\b.*\b(recruiters?|hr|emails?)\b",
     "I won't mass-apply or spam recruiters. That hurts your chances and breaks site rules. I can find your best matches and "
     "apply to each with your confirmation, within your daily limits."),
    (r"\b(fake|invent|fabricate|make up|lie about|inflate|exaggerate)\b.*\b(experience|years|degree|skills?|certifications?|salary|ctc|projects?|company|employer)\b"
     r"|\badd\b.*\b(skills?|experience)\b.*\b(i (don'?t|do not) have|not on my resume)\b",
     "I only use facts from your verified resume and profile. To add a skill you really have, add it with evidence in "
     "Profile → Verified extra skills."),
)
_RULES_RE = [(re.compile(p, re.IGNORECASE | re.DOTALL), msg) for p, msg in _RULES]

_ABUSE = re.compile(r"\b(fuck|bitch|bastard|madarchod|bhenchod|chutiya|asshole)\b", re.IGNORECASE)


@dataclass
class Verdict:
    ok: bool
    text: str  # cleaned input when ok, otherwise the refusal shown to you
    reason: str | None = None


def clean(text: str) -> str:
    """Normalise and strip control characters (keeps newlines), and collapse runs of whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def check(raw: str) -> Verdict:
    text = clean(raw or "")
    if not text:
        return Verdict(False, "Type a message, for example: “find backend jobs in Pune posted this week”.", "empty")
    if len(text) > MAX_CHARS:
        return Verdict(False, f"That message is too long ({len(text)} characters; the limit is {MAX_CHARS}). To import a "
                              "posting, paste its link, or use Jobs → Import for a long description.", "too_long")
    for pattern, message in _RULES_RE:
        if pattern.search(text):
            return Verdict(False, message, "policy")
    if _ABUSE.search(text):
        return Verdict(False, "Let's keep it professional. I'm here to help with your job search whenever you're ready.", "abuse")
    return Verdict(True, text)


_YES = re.compile(r"^\s*(yes|y|yeah|yep|ok|okay|sure|confirm(ed)?|go ahead|do it|proceed|haan|ha|apply( now)?|send( it)?)\s*[.!]*\s*$", re.I)
_NO = re.compile(r"^\s*(no|n|nope|cancel|stop|don'?t|do not|nahi|na|not now|later)\s*[.!]*\s*$", re.I)


def is_yes(text: str) -> bool:
    return bool(_YES.match(text))


def is_no(text: str) -> bool:
    return bool(_NO.match(text))
