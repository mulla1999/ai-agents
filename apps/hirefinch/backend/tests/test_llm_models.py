"""Model dropdown: only text models the key can use, newest generation, recommended first."""

from __future__ import annotations


from hirefinch.errors import ServiceError
from hirefinch.services import llm_models
from hirefinch.services.llm_models import GEMINI_PREFERRED, OPENAI_COMPATIBLE_PREFERRED, rank


def test_gemini_ranking_hides_retired_and_non_text_models():
    names = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.8-flash-tts",
             "gemini-3.1-flash-image", "gemini-3-flash-preview", "gemini-flash-latest", "gemini-3.5-pro"]
    models = rank(names, GEMINI_PREFERRED)
    assert models[0].id == "gemini-3.5-flash" and models[0].recommended and "recommended" in models[0].label
    ids = [m.id for m in models]
    assert "gemini-2.5-flash" not in ids  # listed by Google but refused to new users
    assert not any(x in i for i in ids for x in ("tts", "image", "preview"))
    assert "gemini-flash-latest" in ids and "gemini-3.5-pro" in ids


def test_groq_ranking():
    models = rank(["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "whisper-large-v3", "llama-guard-4-12b"], OPENAI_COMPATIBLE_PREFERRED)
    assert [m.id for m in models] == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


async def test_endpoint_uses_typed_or_saved_key(client, monkeypatch):
    seen = []

    async def fake(key):
        seen.append(key)
        if key == "bad":
            raise ServiceError("bad_key", "Google rejected this API key.", 422)
        return rank(["gemini-3.5-flash", "gemini-3.8-flash"], GEMINI_PREFERRED)

    monkeypatch.setattr(llm_models, "gemini_models", fake)
    assert (await client.post("/api/integrations/llm/models", json={"provider": "gemini"})).status_code == 422  # no key at all
    r = await client.post("/api/integrations/llm/models", json={"provider": "gemini", "api_key": "typed-key"})
    assert r.status_code == 200 and r.json()["recommended"] == "gemini-3.5-flash" and seen[-1] == "typed-key"
    await client.put("/api/integrations/llm", json={"config": {"provider": "gemini", "model": "gemini-3.5-flash"}, "secrets": {"api_key": "saved-key"}})
    r = await client.post("/api/integrations/llm/models", json={"provider": "gemini"})
    assert r.status_code == 200 and seen[-1] == "saved-key"  # the saved key is used, never returned
    assert "saved-key" not in r.text
    r = await client.post("/api/integrations/llm/models", json={"provider": "gemini", "api_key": "bad"})
    assert r.status_code == 422 and "rejected" in r.text


async def test_openai_compatible_refuses_private_hosts(client):
    r = await client.post("/api/integrations/llm/models", json={"provider": "openai_compatible", "api_key": "k", "base_url": "https://127.0.0.1/v1"})
    assert r.status_code == 422
