"""Strip identity numbers from user text before it is stored, logged or sent to an LLM."""

from __future__ import annotations

import re

_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)
# Phone numbers, bank account numbers, card numbers. Incomes never need 9+ digits in rupees here.
_LONG_NUMBER = re.compile(r"(?<!\d)\d{9,19}(?!\d)")


def redact_pii(text: str) -> str:
    text = _AADHAAR.sub("[REDACTED_ID]", text)
    text = _PAN.sub("[REDACTED_ID]", text)
    return _LONG_NUMBER.sub("[REDACTED_NUMBER]", text)
