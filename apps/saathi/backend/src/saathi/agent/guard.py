"""Checks a drafted reply against the facts it was allowed to use.

The persona prompt forbids inventing amounts, phone numbers and links, but a prompt is a request,
not a guarantee. In a welfare assistant a wrong amount or a fake "helpline" or website does real
harm, so every reply is checked here before it is sent:

- every rupee amount, and every number of 5+ digits (helplines, phone numbers, large sums), must
  appear in the allowed facts (scheme data, the person's own messages, their profile);
- every web address must be on a host named in the allowed facts.

Numbers are compared by value, so "Rs 2,00,000", "₹200000" and "2 लाख" are the same, and digits in
Indian scripts are read too. Scheme names are not checked; they are too varied across languages.
"""

from __future__ import annotations

import re
import unicodedata

_MULTIPLIERS = {
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "लाख": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "करोड़": 10_000_000, "करोड": 10_000_000,
    "thousand": 1_000, "hazar": 1_000, "hazaar": 1_000, "हज़ार": 1_000, "हजार": 1_000,
}  # fmt: skip
_CURRENCY_BEFORE = re.compile(r"(?:₹|\brs\.?|\binr|रु\.?|रुपये|रुपए)\s*$", re.IGNORECASE)
_CURRENCY_AFTER = re.compile(r"^\s*(?:rupees?|rs\b|रुपये|रुपए|रुपया)", re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MULTIPLIER_AFTER = re.compile(r"^\s*(" + "|".join(sorted(map(re.escape, _MULTIPLIERS), key=len, reverse=True)) + ")",
                               re.IGNORECASE)  # fmt: skip
_HOST = re.compile(
    r"(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+(?:gov\.in|nic\.in|org\.in|co\.in|in|com|org|net|info))(?![a-z0-9-])",
    re.IGNORECASE,
)
# Phone and helpline numbers written in groups ("1800-180-1551", "+91 98765 43210").
_GROUPED_NUMBER = re.compile(r"\+?\d[\d \-]{8,}\d")
LONG_NUMBER_DIGITS = 5
PHONE_DIGITS = 10


def _ascii_digits(text: str) -> str:
    """Turn digits in any script (Devanagari, Tamil, Bengali, ...) into 0-9."""
    return "".join(str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch for ch in text)


def _numbers(text: str, *, split_groups: bool = False) -> list[tuple[float, bool]]:
    """Every number in the text as (value, must_be_checked).

    A grouped number ("1800-180-1551") counts as one number; with ``split_groups`` its parts are
    also returned, which is what we want for the allowed facts.
    """
    text = _ascii_digits(text)
    found = []
    for match in _GROUPED_NUMBER.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if len(digits) >= PHONE_DIGITS and re.search(r"[ \-]", match.group().strip()):
            found.append((float(digits), True))
            if not split_groups:
                text = text[: match.start()] + " " * len(match.group()) + text[match.end():]
    for match in _NUMBER.finditer(text):
        raw = match.group().rstrip(",")
        digits = raw.replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        after = text[match.end():]
        multiplier = _MULTIPLIER_AFTER.match(after)
        if multiplier:
            value *= _MULTIPLIERS[multiplier.group(1).lower()]
        is_money = bool(
            multiplier
            or _CURRENCY_BEFORE.search(text[max(0, match.start() - 8): match.start()])
            or _CURRENCY_AFTER.match(after)
        )
        long_number = len(digits.split(".")[0]) >= LONG_NUMBER_DIGITS
        found.append((value, is_money or long_number))
    return found


def _show(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _hosts(text: str) -> set[str]:
    return {match.group(1).lower() for match in _HOST.finditer(text)}


def unsupported_facts(reply: str, allowed: str) -> list[str]:
    """Amounts, long numbers and web hosts in ``reply`` that ``allowed`` does not contain."""
    allowed_values = {value for value, _ in _numbers(allowed, split_groups=True)}
    allowed_hosts = _hosts(allowed)
    problems = [
        f"number {_show(value)}" for value, checked in _numbers(reply) if checked and value not in allowed_values
    ]
    for host in sorted(_hosts(reply)):
        if not any(host == ok or host.endswith("." + ok) for ok in allowed_hosts):
            problems.append(f"website {host}")
    return problems
