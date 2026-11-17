"""Which models a user's AI key can actually use, for the model dropdown in Integrations.

Providers retire models (Google stopped offering gemini-2.5-flash to new users), so a fixed list goes
stale. This asks the provider with the user's own key and returns the text models, with the one
that suits HireFinch best (fast, cheap, good at short structured writing) marked as recommended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..errors import ServiceError

# Preferred defaults, best first. The first one the key can use is recommended.
GEMINI_PREFERRED = ("gemini-3.5-flash", "gemini-flash-latest", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-lite-latest")
OPENAI_COMPATIBLE_PREFERRED = ("llama-3.3-70b-versatile", "gpt-5.1-mini", "gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini")
# Not text chat models: speech, images, video, embeddings, live audio, robotics and similar.
_NOT_TEXT = re.compile(r"(tts|image|imagen|veo|embed|aqa|audio|live|vision-only|robotics|computer-use|omni|whisper|guard|"
                       r"moderation|transcribe|realtime|dall-e|sora)", re.I)


@dataclass
class ModelChoice:
    id: str
    label: str
    recommended: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _label(model: str) -> str:
    if model.endswith("-latest"):
        return f"{model} (always the newest)"
    if "lite" in model:
        return f"{model} (lighter, higher free limits)"
    if "pro" in model:
        return f"{model} (strongest, lower free limits)"
    return model


def _version(model: str) -> tuple:
    nums = re.findall(r"\d+(?:\.\d+)?", model)
    return tuple(-float(n) for n in nums[:1]) or (0.0,)


def _major(model: str | None) -> int | None:
    m = re.search(r"-(\d+)(?:\.\d+)?-", f"{model}-") if model else None
    return int(m.group(1)) if m else None


def rank(models: list[str], preferred: tuple[str, ...]) -> list[ModelChoice]:
    """Text models only: the recommended one first, then the rest (newest first)."""
    usable = sorted({m for m in models if not _NOT_TEXT.search(m) and "preview" not in m and "exp" not in m},
                    key=lambda m: (0 if "flash" in m else 1, _version(m), m))
    best = next((p for p in preferred if p in usable), usable[0] if usable else None)
    # Providers still list retired generations they refuse to serve (e.g. gemini-2.5-flash for new
    # users), so hide anything older than the recommended model's generation. "-latest" aliases stay.
    floor = _major(best) if best else None
    if floor is not None:
        usable = [m for m in usable if m.endswith("-latest") or (_major(m) or floor) >= floor]
    ordered = ([best] if best else []) + [m for m in usable if m != best]
    return [ModelChoice(m, _label(m) + (" · recommended" if m == best else ""), m == best) for m in ordered]


async def gemini_models(api_key: str) -> list[ModelChoice]:
    from google import genai
    from google.genai import errors

    client = genai.Client(api_key=api_key)
    names: list[str] = []
    try:
        async for m in await client.aio.models.list():
            # Standard Flash and Pro families only (codenamed experiments such as "gemini-4-argon" are left out).
            if ("generateContent" in (m.supported_actions or []) and m.name.startswith("models/gemini")
                    and re.search(r"-(flash|pro)(-|$)", m.name)):
                names.append(m.name.removeprefix("models/"))
    except errors.APIError as exc:
        raise ServiceError("bad_key", "Google rejected this API key. Check it, or create a new free one in AI Studio.", 422) from exc
    if not names:
        raise ServiceError("no_models", "this key has no Gemini text models available", 422)
    return rank(names, GEMINI_PREFERRED)


async def openai_compatible_models(http: httpx.AsyncClient, base_url: str, api_key: str) -> list[ModelChoice]:
    try:
        response = await http.get(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"},
                                  timeout=15, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ServiceError("unreachable", f"could not reach {base_url}", 502) from exc
    if response.status_code in (401, 403):
        raise ServiceError("bad_key", "the provider rejected this API key", 422)
    if response.status_code >= 400:
        raise ServiceError("bad_response", f"the provider answered HTTP {response.status_code}", 502)
    names = [str(m.get("id")) for m in (response.json().get("data") or []) if m.get("id")]
    return rank(names, OPENAI_COMPATIBLE_PREFERRED)
