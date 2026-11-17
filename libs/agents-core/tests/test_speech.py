import base64
import json
import shutil

import httpx
import pytest

from agents_core.speech import SpeechError, SpeechSettings, create_speech, language_code, to_ogg_opus, to_wav_16k
from agents_core.speech.azure import AzureSpeechProvider
from agents_core.speech.bhashini import CONFIG_URL, BhashiniSpeechProvider


@pytest.mark.parametrize(
    ("name", "code"),
    [("Hindi (Devanagari script)", "hi"), ("Hindi in Latin script (Hinglish)", "hi"), ("Tamil", "ta"),
     ("বাংলা", "bn"), ("English", "en"), ("Klingon", "hi"), (None, "hi"), ("ta", "ta")],
)  # fmt: skip
def test_language_code(name, code):
    assert language_code(name) == code


def mock_http(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_azure_transcribe_and_synthesize():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "stt.speech" in request.url.host:
            return httpx.Response(200, json={"RecognitionStatus": "Success", "DisplayText": "मेरी उम्र 60 है"})
        return httpx.Response(200, content=b"OGGDATA")

    provider = AzureSpeechProvider(key="k", region="centralindia", http=mock_http(handler))
    assert await provider.transcribe(b"wav", "hi") == "मेरी उम्र 60 है"
    assert seen[0].url.params["language"] == "hi-IN"
    assert seen[0].headers["Ocp-Apim-Subscription-Key"] == "k"

    audio = await provider.synthesize("नमस्ते <&>", "hi")
    assert audio.content == b"OGGDATA" and audio.mime_type == "audio/ogg"
    assert b"hi-IN-SwaraNeural" in seen[1].content and b"&lt;&amp;&gt;" in seen[1].content  # text is XML-escaped
    assert await provider.synthesize("hello", "xx") is None


async def test_azure_no_match_is_empty_and_errors_raise():
    provider = AzureSpeechProvider(
        key="k", region="r", http=mock_http(lambda r: httpx.Response(200, json={"RecognitionStatus": "NoMatch"}))
    )
    assert await provider.transcribe(b"wav", "ta") == ""
    failing = AzureSpeechProvider(key="k", region="r", http=mock_http(lambda r: httpx.Response(401)))
    with pytest.raises(SpeechError):
        await failing.transcribe(b"wav", "hi")


async def test_bhashini_config_then_compute_with_cache():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        if str(request.url) == CONFIG_URL:
            assert request.headers["userID"] == "u" and request.headers["ulcaApiKey"] == "k"
            return httpx.Response(200, json={
                "pipelineResponseConfig": [{"config": [{"serviceId": "ai4bharat/conformer-hi-gpu--t4"}]}],
                "pipelineInferenceAPIEndPoint": {
                    "callbackUrl": "https://dhruva.example/services/inference/pipeline",
                    "inferenceApiKey": {"name": "Authorization", "value": "secret"},
                },
            })  # fmt: skip
        assert request.headers["Authorization"] == "secret"
        task = body["pipelineTasks"][0]
        assert task["config"]["serviceId"] == "ai4bharat/conformer-hi-gpu--t4"
        assert base64.b64decode(body["inputData"]["audio"][0]["audioContent"]) == b"wav"
        return httpx.Response(200, json={"pipelineResponse": [{"output": [{"source": "नमस्ते"}]}]})

    provider = BhashiniSpeechProvider(http=mock_http(handler), user_id="u", ulca_api_key="k")
    assert await provider.transcribe(b"wav", "hi") == "नमस्ते"
    assert await provider.transcribe(b"wav", "hi") == "नमस्ते"
    assert [str(c.url) for c in calls].count(CONFIG_URL) == 1  # config cached


async def test_bhashini_self_hosted_needs_no_config_call():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://dhruva.local/pipeline"
        return httpx.Response(200, json={"pipelineResponse": [{"output": [{"source": "vanakkam"}]}]})

    provider = BhashiniSpeechProvider(
        http=mock_http(handler), inference_url="http://dhruva.local/pipeline", service_ids={"asr:ta": "ta-model"}
    )
    assert await provider.transcribe(b"wav", "ta") == "vanakkam"
    with pytest.raises(SpeechError):
        await provider.transcribe(b"wav", "hi")  # no serviceId configured
    assert await provider.synthesize("x", "ta") is None


def test_speech_settings_factory():
    http = httpx.AsyncClient()
    assert create_speech(SpeechSettings(_env_file=None), http) is None
    with pytest.raises(SpeechError, match="AZURE_SPEECH_KEY"):
        create_speech(SpeechSettings(_env_file=None, speech_provider="azure"), http)
    with pytest.raises(SpeechError, match="ULCA"):
        create_speech(SpeechSettings(_env_file=None, speech_provider="bhashini"), http)
    with pytest.raises(SpeechError, match="unknown"):
        create_speech(SpeechSettings(_env_file=None, speech_provider="nope"), http)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_ffmpeg_round_trip():
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 2 * 44100)  # 1 s of stereo silence
    ogg = await to_ogg_opus(buffer.getvalue())
    assert ogg[:4] == b"OggS"
    wav = await to_wav_16k(ogg)
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 16000)
