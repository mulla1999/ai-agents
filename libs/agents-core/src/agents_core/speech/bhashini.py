"""Bhashini (MeitY) speech, or a self-hosted AI4Bharat Dhruva-Platform server, which serves the same API.

Hosted Bhashini: two calls. A config call (``getModelsPipeline``, authenticated with the ULCA user ID
and API key) returns the inference endpoint, its key and the serviceId for a task and language; the
compute call then does the work. Config results are cached per task and language.

Self-hosted Dhruva: set ``inference_url`` and ``inference_api_key`` and pass ``service_ids``; no
config call is made.

Note: Bhashini's free API access is intended for proof-of-concept use; check the current terms with
the Bhashini team before production use.
"""

from __future__ import annotations

import base64
import time

import httpx

from .audio import to_ogg_opus
from .base import SpeechError, SpeechProvider, SynthesizedAudio

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
DEFAULT_PIPELINE_ID = "64392f96daac500b55c543cd"  # AI4Bharat ASR / NMT / TTS
_CONFIG_TTL = 6 * 60 * 60


class BhashiniSpeechProvider(SpeechProvider):
    name = "bhashini"

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        user_id: str | None = None,
        ulca_api_key: str | None = None,
        pipeline_id: str = DEFAULT_PIPELINE_ID,
        inference_url: str | None = None,
        inference_api_key: str | None = None,
        service_ids: dict[str, str] | None = None,
        tts_gender: str = "female",
    ) -> None:
        if not inference_url and not (user_id and ulca_api_key):
            raise SpeechError("Bhashini needs a ULCA user ID and API key, or a self-hosted inference URL")
        self._http = http
        self._user_id = user_id
        self._ulca_api_key = ulca_api_key
        self._pipeline_id = pipeline_id
        self._inference_url = inference_url
        self._inference_api_key = inference_api_key
        self._service_ids = service_ids or {}  # e.g. {"asr:hi": "ai4bharat/conformer-hi-gpu--t4"}
        self._tts_gender = tts_gender
        self._cache: dict[str, tuple[float, str, dict[str, str], str]] = {}

    async def transcribe(self, wav_16k: bytes, language: str) -> str:
        url, headers, service_id = await self._endpoint("asr", language)
        data = await self._compute(
            url,
            headers,
            {
                "pipelineTasks": [
                    {
                        "taskType": "asr",
                        "config": {
                            "language": {"sourceLanguage": language},
                            "serviceId": service_id,
                            "audioFormat": "wav",
                            "samplingRate": 16000,
                        },
                    }
                ],
                "inputData": {"audio": [{"audioContent": base64.b64encode(wav_16k).decode()}]},
            },
        )
        try:
            return data["pipelineResponse"][0]["output"][0]["source"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise SpeechError("unexpected Bhashini ASR response") from exc

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio | None:
        try:
            url, headers, service_id = await self._endpoint("tts", language)
        except SpeechError:
            return None  # no voice for this language
        data = await self._compute(
            url,
            headers,
            {
                "pipelineTasks": [
                    {
                        "taskType": "tts",
                        "config": {
                            "language": {"sourceLanguage": language},
                            "serviceId": service_id,
                            "gender": self._tts_gender,
                            "samplingRate": 16000,
                        },
                    }
                ],
                "inputData": {"input": [{"source": text}]},
            },
        )
        try:
            audio = base64.b64decode(data["pipelineResponse"][0]["audio"][0]["audioContent"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SpeechError("unexpected Bhashini TTS response") from exc
        return SynthesizedAudio(await to_ogg_opus(audio), "audio/ogg")

    async def _compute(self, url: str, headers: dict[str, str], body: dict) -> dict:
        response = await self._http.post(url, headers=headers, json=body, timeout=60)
        if response.status_code != 200:
            raise SpeechError(f"Bhashini compute call failed with HTTP {response.status_code}")
        return response.json()

    async def _endpoint(self, task: str, language: str) -> tuple[str, dict[str, str], str]:
        key = f"{task}:{language}"
        if self._inference_url:
            if key not in self._service_ids:
                raise SpeechError(f"no serviceId configured for {key}")
            headers = {"Authorization": self._inference_api_key} if self._inference_api_key else {}
            return self._inference_url, headers, self._service_ids[key]

        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1], cached[2], cached[3]

        response = await self._http.post(
            CONFIG_URL,
            headers={"userID": self._user_id, "ulcaApiKey": self._ulca_api_key},
            json={
                "pipelineTasks": [{"taskType": task, "config": {"language": {"sourceLanguage": language}}}],
                "pipelineRequestConfig": {"pipelineId": self._pipeline_id},
            },
            timeout=20,
        )
        if response.status_code != 200:
            raise SpeechError(f"Bhashini config call failed with HTTP {response.status_code}")
        try:
            data = response.json()
            endpoint = data["pipelineInferenceAPIEndPoint"]
            auth = endpoint["inferenceApiKey"]
            service_id = self._service_ids.get(key) or data["pipelineResponseConfig"][0]["config"][0]["serviceId"]
            result = (endpoint["callbackUrl"], {auth["name"]: auth["value"]}, service_id)
        except (KeyError, IndexError, TypeError) as exc:
            raise SpeechError(f"Bhashini has no {task} model for language {language!r}") from exc
        self._cache[key] = (time.monotonic() + _CONFIG_TTL, *result)
        return result
