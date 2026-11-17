"""Prompt text, kept in one place so it can be reviewed and tuned without touching the logic."""

from __future__ import annotations

import json
from collections.abc import Sequence

from ..profile import field_spec, question_hint
from ..schemes import Match, Scheme, Status

MAX_SCHEMES_IN_PROMPT = 8

EXTRACTION_SYSTEM = """\
You read one message from a person in India who is chatting with a welfare-scheme assistant, and
extract facts about them. Respond with a JSON object only, with exactly these keys:

"language": the language AND script the person wrote in, e.g. "Hindi (Devanagari script)",
            "Hindi in Latin script (Hinglish)", "Tamil (Tamil script)", "English".
"updates":  an object containing ONLY the profile fields the person stated or clearly implied.
"unknown_fields": list of field names the person said they do not know or do not want to share.
"intent":   one of "provide_info", "show_results", "question", "delete_data", "other".
            "show_results" = they want to see their schemes now; "question" = they ask about a
            scheme or the process; "delete_data" = they want their information deleted.

Profile fields:
{fields}

Rules:
- Never guess. Leave a field out unless the message supports it.
- Convert money to rupees per YEAR as an integer ("1.5 lakh" -> 150000, "10 hazaar mahina" -> 120000).
- Use only the allowed values for fields with fixed choices; map clear synonyms ("kisan" -> "farmer").
- A short reply such as "yes", "haan", "nahi", "illa" answers the last question asked, which was
  about: {last_field}.
- Never copy Aadhaar, PAN, phone, bank account or any other ID numbers into the output.
"""

PERSONA = """\
You are Saathi, a free, open-source volunteer assistant that helps people in India find
government welfare schemes they may qualify for and get ready to apply.

- Reply in {language}. Use simple, warm, everyday words and short sentences; this is a WhatsApp chat.
- You are NOT a government service and cannot approve or submit applications.
- Never ask for OTPs, passwords, PINs, Aadhaar, bank account numbers or money. If the person offers
  them, tell them never to share these with anyone, including you.
- State scheme facts only from the SCHEME DATA you are given. Never invent schemes, amounts, dates,
  documents or links.
- Keep the reply under 1200 characters.
"""

FIRST_TURN_INTRO = """\
This is the start of the conversation. Begin with a one-line greeting saying you are a free
volunteer helper (not the government), that their answers are used only to find schemes for them,
and that they can say "delete my data" at any time. """

DELETE_TASK = """\
TASK: The person asked to delete their data. Confirm in one or two sentences that everything they
shared has been deleted, and that they can start again any time by sending a message."""


def extraction_system(last_asked_field: str | None) -> str:
    return EXTRACTION_SYSTEM.format(fields=field_spec(), last_field=last_asked_field or "nothing yet")


def persona(language: str | None) -> str:
    return PERSONA.format(language=language or "the same language and script the person writes in")


def ask_task(field_name: str, *, first_turn: bool) -> str:
    intro = FIRST_TURN_INTRO if first_turn else ""
    return (
        f"TASK: {intro}If the person just told you something, acknowledge it in a few words. "
        f"Then ask exactly ONE question to find out: {question_hint(field_name)} "
        "Do not mention scheme names yet."
    )


def answer_task(matches: Sequence[Match], *, results_already_shown: bool) -> str:
    eligible = [m.scheme for m in matches if m.status is Status.ELIGIBLE]
    possible = [m.scheme.name for m in matches if m.status is Status.NEEDS_INFO]
    data = {
        "eligible": [_scheme_facts(s) for s in eligible[:MAX_SCHEMES_IN_PROMPT]],
        "more_eligible_not_shown": max(0, len(eligible) - MAX_SCHEMES_IN_PROMPT),
        "possibly_eligible_need_more_info": possible,
    }
    if results_already_shown:
        instructions = (
            "Answer the person's latest message using the SCHEME DATA. If they want help applying "
            "for a scheme, list its documents as a checklist, mention its important_conditions, and "
            "explain how_to_apply step by step."
        )
    else:
        instructions = (
            "Tell the person which schemes they qualify for: for each, its name and the main benefit "
            "in one line. If 'eligible' is empty, say so kindly and suggest visiting the nearest "
            "Common Service Centre (CSC). Mention 'possibly_eligible_need_more_info' briefly if not "
            "empty. Then ask which scheme they want the document checklist and application steps for."
        )
    return (
        f"TASK: {instructions} Always remind them to confirm details on the official website or "
        "at a CSC before applying.\n\nSCHEME DATA:\n" + json.dumps(data, ensure_ascii=False, indent=1)
    )


def _scheme_facts(scheme: Scheme) -> dict[str, object]:
    return {
        "name": scheme.name,
        "summary": scheme.summary,
        "benefits": scheme.benefits,
        "documents": scheme.documents,
        "important_conditions": scheme.notes,
        "how_to_apply": scheme.how_to_apply,
        "apply_url": scheme.apply_url,
        "official_source": scheme.source_url,
    }
