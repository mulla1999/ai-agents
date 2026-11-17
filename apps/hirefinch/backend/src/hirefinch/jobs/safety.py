"""Untrusted-content checks for job postings.

Job descriptions, web pages and emails are data, never instructions. This module flags two things:

* **prompt injection**: text that tries to instruct an AI (often hidden in HTML). The job is still
  shown, but it is excluded from automatic actions and LLM steps see it only as quoted data.
* **suspicious listings**: fees, chat-app-only contact, unrealistic pay, missing company. These are
  excluded from automatic actions and flagged for your review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_INJECTION = (
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (all |any )?(the )?(previous|prior|above|earlier|your) (instructions|rules|guidelines)",
    r"forget (all |your )?(previous |prior )?instructions",
    r"\byou are (now )?(an? )?(ai|assistant|language model|chatbot|gpt)\b",
    r"\b(system|developer) prompt\b",
    r"\bas an ai (language )?model\b",
    r"<\|?(im_start|im_end|system|endoftext)\|?>",
    r"^\s*(system|assistant)\s*:",
    r"\b(ai|llm|bot|agent|assistant)s?,? (must|should|please) (rate|score|rank|mark|approve|select)\b",
    r"\b(rate|score|rank) (this|the) (candidate|applicant|resume) (as )?(highly|100|10/10|top)\b",
    r"\b(reveal|print|send|share|output) (your |the )?(api[ _-]?keys?|password|credentials|secrets?|tokens?|system prompt)\b",
    r"\bexecute (the following|this) (command|code|script)\b",
    r"\b(curl|wget)\s+https?://",
    r"\bapply to all (jobs|positions)\b",
)
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION), re.IGNORECASE | re.MULTILINE)

_SUSPICIOUS = (
    (r"\b(registration|processing|training|security|joining|application) (fee|deposit|charges?)\b", "asks for a fee"),
    (r"\b(pay|deposit) (rs\.?|inr|₹|\$)\s?\d+", "asks for a payment"),
    (r"\b(contact|message|reach) (us |hr )?(only )?(on|via) (telegram|whatsapp)\b", "contact only via chat app"),
    (r"\bearn (rs\.?|inr|₹|\$)\s?\d[\d,]* (per|a) (day|hour)\b", "unrealistic pay claim"),
    (r"\bno (interview|experience) (required|needed)\b.*\b(earn|income)\b", "too-good-to-be-true offer"),
    (r"\b(aadhaar|pan card|bank account) (details|number) (required|needed) (to|for) apply\b", "asks for identity documents to apply"),
)
_SUSPICIOUS_RE = [(re.compile(p, re.IGNORECASE), label) for p, label in _SUSPICIOUS]
_PERSONAL_DOMAINS = frozenset({"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com",
                               "proton.me", "protonmail.com", "icloud.com"})


@dataclass
class SafetyReport:
    prompt_injection: bool = False
    injection_snippets: list[str] = field(default_factory=list)
    suspicious: bool = False
    suspicious_reasons: list[str] = field(default_factory=list)

    def as_flags(self) -> dict[str, object]:
        return {
            "prompt_injection": self.prompt_injection,
            "injection_snippets": self.injection_snippets[:3],
            "suspicious": self.suspicious,
            "suspicious_reasons": self.suspicious_reasons,
        }


def scan(visible_text: str, hidden_text: str = "", *, company: str = "", emails: list[str] | None = None) -> SafetyReport:
    report = SafetyReport()
    for text in (visible_text, hidden_text):
        for m in _INJECTION_RE.finditer(text):
            report.prompt_injection = True
            start = max(0, m.start() - 40)
            report.injection_snippets.append(text[start : m.end() + 40].replace("\n", " ").strip())
    if hidden_text.strip() and len(hidden_text.split()) > 8:
        report.prompt_injection = True
        report.injection_snippets.append("hidden text in the job page: " + hidden_text[:120])
    for pattern, label in _SUSPICIOUS_RE:
        if pattern.search(visible_text):
            report.suspicious_reasons.append(label)
    if not company.strip() or company.strip().lower() in {"confidential", "unknown", "n/a", "company"}:
        report.suspicious_reasons.append("company name is missing")
    for email in emails or []:
        if email.split("@")[-1].lower() in _PERSONAL_DOMAINS:
            report.suspicious_reasons.append(f"applications go to a personal email domain ({email.split('@')[-1]})")
            break
    report.suspicious = bool(report.suspicious_reasons)
    return report


def quote_untrusted(label: str, text: str, limit: int = 12000) -> str:
    """Wrap untrusted text for an LLM prompt so it is read as data. Closing tags inside are defused."""
    safe = text[:limit].replace(f"</{label}>", f"<\\/{label}>")
    return f"<{label}>\n{safe}\n</{label}>"
