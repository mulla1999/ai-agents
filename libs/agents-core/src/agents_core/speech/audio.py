"""Audio conversion with ffmpeg (must be installed; the Docker images include it)."""

from __future__ import annotations

import asyncio

from .base import SpeechError

MAX_SECONDS = 60  # longest voice note we transcribe; the rest is cut off


async def _ffmpeg(args: list[str], audio: bytes) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
    except FileNotFoundError as exc:
        raise SpeechError("ffmpeg is not installed") from exc
    out, err = await asyncio.wait_for(process.communicate(audio), timeout=60)
    if process.returncode != 0 or not out:
        raise SpeechError(f"ffmpeg failed: {err.decode(errors='replace')[:200]}")
    return out


async def to_wav_16k(audio: bytes) -> bytes:
    """Any input (e.g. WhatsApp OGG/Opus) -> 16 kHz mono 16-bit WAV, at most MAX_SECONDS long."""
    return await _ffmpeg(["-t", str(MAX_SECONDS), "-ac", "1", "-ar", "16000", "-f", "wav"], audio)


async def to_ogg_opus(audio: bytes) -> bytes:
    """Any input -> OGG/Opus mono, the format WhatsApp plays as a voice message."""
    return await _ffmpeg(["-ac", "1", "-c:a", "libopus", "-b:a", "24k", "-f", "ogg"], audio)
