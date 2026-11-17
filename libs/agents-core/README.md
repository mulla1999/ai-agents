# agents-core

Shared building blocks for every agent in this workspace. Code goes here only when more than one
agent needs it; anything specific to one agent stays in that agent's package.

| Module | What it gives you |
|---|---|
| `agents_core.llm` | One `LLMProvider` interface, with Azure OpenAI, Gemini and OpenAI-compatible backends chosen by `LLM_PROVIDER` |
| `agents_core.llm.testing` | `ScriptedLLM`, a fake provider for tests that need no network or keys |
| `agents_core.privacy` | `redact_pii()`: strips Aadhaar, PAN, phone and account numbers from text |
| `agents_core.channels.whatsapp` | Signed WhatsApp Cloud API webhook router and send client |

```python
from agents_core.llm import LLMSettings, Message, create_llm

llm = create_llm(LLMSettings())                                       # provider from LLM_PROVIDER
gemini = create_llm(LLMSettings().model_copy(update={"llm_provider": "gemini"}))
reply = await llm.complete([Message("user", "नमस्ते")])
data = await llm.complete_json([Message("system", "Reply as JSON ..."), Message("user", "...")])
```

To add a backend, subclass `LLMProvider` (one async `complete` method) and register a builder
with `@register_provider("name")` in `agents_core/llm/factory.py`.
