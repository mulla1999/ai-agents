"""Prompt text, kept in one place so it can be reviewed and tuned without touching the logic."""

from __future__ import annotations

import json
from collections.abc import Sequence

from ..profile import FamilyMember, field_spec, question_hint
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

Profile fields (about the person who is writing):
{fields}

"updates" may also contain "family_members": a list of family members the person mentions, each an
object with "relation" (one of spouse, son, daughter, father, mother, other) and any of "age",
"gender", "is_studying_post_matric", "is_widow", "is_pregnant_or_lactating", "disability_percent",
"is_government_employee".
List only members mentioned in THIS message. To add facts about a known member, repeat their
relation and age. Never include names. Known family members: {family}

Rules:
- Never guess. Leave a field out unless the message supports it.
- Convert money to rupees per YEAR as an integer ("1.5 lakh" -> 150000, "10 hazaar mahina" -> 120000).
- Convert land to hectares: 1 acre = 0.4047 hectare ("5 acre" -> 2.02). If a local unit such as bigha
  or kanal is used, leave land_holding_hectares out (its size differs from state to state).
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


DELETE_FALLBACK = (
    "Everything you shared has been deleted. Send a message any time to start again.\n"
    "आपकी दी हुई सारी जानकारी हटा दी गई है। फिर से शुरू करने के लिए कभी भी संदेश भेजें।"
)

_CHECK_OFFICIAL = (
    "Please confirm the details on the official website or at a Common Service Centre (CSC) before applying.\n"
    "आवेदन से पहले आधिकारिक वेबसाइट या नज़दीकी CSC पर जानकारी की पुष्टि ज़रूर करें।"
)


def correction(problems: Sequence[str]) -> str:
    return (
        "CORRECTION: your previous draft contained facts that are not in the SCHEME DATA or in what the "
        f"person said: {'; '.join(problems)}. Write the reply again without them. Do not give any amount, "
        "phone number, helpline or website that is not written in the SCHEME DATA."
    )


def question_fallback(field_name: str) -> str:
    """Sent when the model keeps adding unsupported facts while asking a question."""
    return question_hint(field_name)


def answer_fallback(matches: Sequence[Match]) -> str:
    """A plain reply built only from scheme data, used when the model keeps adding unsupported facts."""
    eligible = _eligible_by_scheme(matches)[:MAX_SCHEMES_IN_PROMPT]
    if not eligible:
        return (
            "I could not find a scheme you clearly qualify for yet. A Common Service Centre (CSC) can help you check.\n"
            "अभी मुझे ऐसी कोई योजना नहीं मिली जिसके लिए आप साफ़ तौर पर पात्र हों। नज़दीकी CSC पर जाँच करवा सकते हैं।"
        )
    lines = ["Schemes you may qualify for / आप इन योजनाओं के लिए पात्र हो सकते हैं:"]
    for scheme, who in eligible:
        link = scheme.apply_url or scheme.source_url
        lines.append(f"• {scheme.name} (for {', '.join(who)}): {scheme.benefits} ({link})")
    lines.append(_CHECK_OFFICIAL)
    return "\n".join(lines)


def extraction_system(last_asked_field: str | None, family: Sequence[FamilyMember] = ()) -> str:
    known = json.dumps([m.model_dump(mode="json", exclude_none=True) for m in family]) if family else "none yet"
    return EXTRACTION_SYSTEM.format(fields=field_spec(), last_field=last_asked_field or "nothing yet", family=known)


def persona(language: str | None) -> str:
    return PERSONA.format(language=language or "the same language and script the person writes in")


def ask_task(field_name: str, *, first_turn: bool) -> str:
    intro = FIRST_TURN_INTRO if first_turn else ""
    return (
        f"TASK: {intro}If the person just told you something, acknowledge it in a few words. "
        f"Then ask exactly ONE question to find out: {question_hint(field_name)} "
        "Do not mention scheme names yet."
    )


def _eligible_by_scheme(matches: Sequence[Match]) -> list[tuple[Scheme, list[str]]]:
    """Eligible schemes, each with who qualifies ("you", "daughter, age 6", ...), in first-seen order."""
    grouped: dict[str, tuple[Scheme, list[str]]] = {}
    for match in matches:
        if match.status is Status.ELIGIBLE:
            who = "you" if match.member is None else f"your {match.member.label()}"
            grouped.setdefault(match.scheme.id, (match.scheme, []))[1].append(who)
    return list(grouped.values())


def answer_task(matches: Sequence[Match], *, results_already_shown: bool) -> str:
    eligible = _eligible_by_scheme(matches)
    possible = [m.scheme.name for m in matches if m.status is Status.NEEDS_INFO and m.member is None]
    family_possible = [
        {"scheme": m.scheme.name, "for": f"your {m.member.label()}", "need_to_know": sorted(m.missing_fields)}
        for m in matches
        if m.status is Status.NEEDS_INFO and m.member is not None
    ][:MAX_SCHEMES_IN_PROMPT]
    data = {
        "eligible": [{**_scheme_facts(s), "for": who} for s, who in eligible[:MAX_SCHEMES_IN_PROMPT]],
        "more_eligible_not_shown": max(0, len(eligible) - MAX_SCHEMES_IN_PROMPT),
        "possibly_eligible_need_more_info": possible,
        "family_members_may_qualify": family_possible,
    }
    if results_already_shown:
        instructions = (
            "Answer the person's latest message using the SCHEME DATA. If they want help applying "
            "for a scheme, list its documents as a checklist, mention its important_conditions, and "
            "explain how_to_apply step by step."
        )
    else:
        instructions = (
            "Tell the person which schemes they qualify for: for each, its name, who it is for (the "
            "'for' list: the person and/or named family members) and the main benefit in one line. "
            "If 'eligible' is empty, say so kindly and suggest visiting the nearest Common Service "
            "Centre (CSC). Mention 'possibly_eligible_need_more_info' and 'family_members_may_qualify' "
            "briefly if not empty. Then ask which scheme they want the document checklist and "
            "application steps for."
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
