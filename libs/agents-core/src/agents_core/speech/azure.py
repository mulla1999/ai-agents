"""Azure AI Speech via REST: short-audio speech-to-text (max 60 s) and neural text-to-speech."""

from __future__ import annotations

from xml.sax.saxutils import escape

import httpx

from .base import SpeechError, SpeechProvider, SynthesizedAudio

# Locale and a default neural voice per language. Override voices with AZURE_SPEECH_VOICES.
LOCALES = {
    "hi": ("hi-IN", "hi-IN-SwaraNeural"),
    "bn": ("bn-IN", "bn-IN-TanishaaNeural"),
    "ta": ("ta-IN", "ta-IN-PallaviNeural"),
    "te": ("te-IN", "te-IN-ShrutiNeural"),
    "mr": ("mr-IN", "mr-IN-AarohiNeural"),
    "gu": ("gu-IN", "gu-IN-DhwaniNeural"),
    "kn": ("kn-IN", "kn-IN-SapnaNeural"),
    "ml": ("ml-IN", "ml-IN-SobhanaNeural"),
    "pa": ("pa-IN", "pa-IN-VaaniNeural"),
    "or": ("or-IN", "or-IN-SubhasiniNeural"),
    "as": ("as-IN", "as-IN-YashicaNeural"),
    "ur": ("ur-IN", "ur-IN-GulNeural"),
    "en": ("en-IN", "en-IN-NeerjaNeural"),
}


class AzureSpeechProvider(SpeechProvider):
    name = "azure"

    def __init__(self, *, key: str, region: str, http: httpx.AsyncClient, voices: dict[str, str] | None = None):
        self._key = key
        self._stt_url = f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        self._tts_url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        self._http = http
        self._voices = {code: voice for code, (_, voice) in LOCALES.items()} | (voices or {})

    async def transcribe(self, wav_16k: bytes, language: str) -> str:
        locale = LOCALES.get(language, LOCALES["hi"])[0]
        response = await self._http.post(
            self._stt_url,
            params={"language": locale, "format": "simple"},
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Accept": "application/json",
            },
            content=wav_16k,
            timeout=60,
        )
        if response.status_code != 200:
            raise SpeechError(f"Azure speech-to-text failed with HTTP {response.status_code}")
        data = response.json()
        return data.get("DisplayText", "") if data.get("RecognitionStatus") == "Success" else ""

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio | None:
        if language not in LOCALES:
            return None
        locale, _ = LOCALES[language]
        ssml = (
            f"<speak version='1.0' xml:lang='{locale}'>"
            f"<voice name='{escape(self._voices[language])}'>{escape(text)}</voice></speak>"
        )
        response = await self._http.post(
            self._tts_url,
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "ogg-16khz-16bit-mono-opus",
                "User-Agent": "saathi",
            },
            content=ssml.encode(),
            timeout=60,
        )
        if response.status_code != 200:
            raise SpeechError(f"Azure text-to-speech failed with HTTP {response.status_code}")
        return SynthesizedAudio(response.content, "audio/ogg")
