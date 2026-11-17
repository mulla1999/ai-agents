"""The one interface agents use for speech-to-text and text-to-speech."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class SpeechError(RuntimeError):
    """The speech service could not be reached or returned something unusable."""


@dataclass(frozen=True)
class SynthesizedAudio:
    content: bytes
    mime_type: str  # e.g. "audio/ogg" (Opus) — what WhatsApp accepts for voice messages


class SpeechProvider(ABC):
    """Adapter for one speech backend. Implementations must be safe to share across requests.

    ``language`` is an ISO 639-1 code such as "hi", "ta", "bn" (see ``agents_core.speech.languages``).
    Input audio is always 16 kHz mono WAV; use ``agents_core.speech.audio.to_wav_16k`` first.
    """

    name: str

    @abstractmethod
    async def transcribe(self, wav_16k: bytes, language: str) -> str:
        """Return the transcript, or an empty string if nothing was recognised."""

    @abstractmethod
    async def synthesize(self, text: str, language: str) -> SynthesizedAudio | None:
        """Return spoken audio, or None if this language has no voice."""
