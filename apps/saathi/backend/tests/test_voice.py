import pytest
from agents_core.channels.whatsapp import IncomingMessage
from agents_core.speech import SpeechError, SpeechProvider, SynthesizedAudio

from saathi.app import create_app
from saathi.services import whatsapp as wa_module
from saathi.services.whatsapp import NOT_HEARD


class FakeSpeech(SpeechProvider):
    name = "fake"

    def __init__(self, transcript: str = "मेरी उम्र 62 है", fail: bool = False):
        self.transcript, self.fail = transcript, fail
        self.heard: list[tuple[bytes, str]] = []
        self.spoken: list[tuple[str, str]] = []

    async def transcribe(self, wav_16k: bytes, language: str) -> str:
        if self.fail:
            raise SpeechError("down")
        self.heard.append((wav_16k, language))
        return self.transcript

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio | None:
        self.spoken.append((text, language))
        return SynthesizedAudio(b"OGG", "audio/ogg")


class FakeWhatsApp:
    def __init__(self):
        self.audio_sent: list[tuple[str, bytes, str]] = []

    async def download_media(self, media_id: str, **_):
        return b"opus-bytes", "audio/ogg"

    async def send_audio(self, to: str, audio: bytes, mime_type: str) -> None:
        self.audio_sent.append((to, audio, mime_type))


@pytest.fixture(autouse=True)
def _no_ffmpeg(monkeypatch):
    async def passthrough(audio: bytes) -> bytes:
        return b"wav:" + audio

    monkeypatch.setattr(wa_module, "to_wav_16k", passthrough)


def voice(sender="919876500001"):
    return IncomingMessage("v1", sender, "audio", None, "media-1", "audio/ogg; codecs=opus")


def text(body, sender="919876500001"):
    return IncomingMessage("t1", sender, "text", body)


def build(settings, sessionmaker, llm, sms, speech):
    client = FakeWhatsApp()
    app = create_app(settings, sessionmaker=sessionmaker, llm=llm, sms_sender=sms, speech=speech, whatsapp_client=client)
    return app.state.whatsapp_handler, client


async def test_voice_note_is_transcribed_answered_and_spoken(settings, sessionmaker, llm, sms):
    speech = FakeSpeech()
    handler, client = build(settings, sessionmaker, llm, sms, speech)
    await handler(text("hi"))  # consent notice
    await handler(text("haan"))  # consent

    llm.json_replies = [{"language": "Tamil", "updates": {"age": 62}}]
    reply = await handler(voice())

    assert reply == "REPLY"
    assert speech.heard == [(b"wav:opus-bytes", "hi")]  # language unknown yet: default Hindi
    assert llm.calls[0][0][-1].content == "मेरी उम्र 62 है"  # the transcript went to the agent
    assert speech.spoken == [("REPLY", "ta")]  # replied in the language the person used
    assert client.audio_sent == [("919876500001", b"OGG", "audio/ogg")]

    llm.json_replies = [{}]
    await handler(voice())
    assert speech.heard[-1][1] == "ta"  # next voice note is recognised in Tamil


async def test_voice_before_consent_gets_the_consent_notice(settings, sessionmaker, llm, sms):
    handler, client = build(settings, sessionmaker, llm, sms, FakeSpeech())
    assert "Reply YES" in await handler(voice())
    assert client.audio_sent == []


async def test_unclear_or_failed_transcription(settings, sessionmaker, llm, sms):
    handler, _ = build(settings, sessionmaker, llm, sms, FakeSpeech(transcript="  "))
    await handler(text("hi"))
    await handler(text("yes"))
    assert await handler(voice()) == NOT_HEARD

    handler, _ = build(settings, sessionmaker, llm, sms, FakeSpeech(fail=True))
    assert await handler(voice()) == NOT_HEARD
    assert llm.calls == []  # nothing reached the LLM
