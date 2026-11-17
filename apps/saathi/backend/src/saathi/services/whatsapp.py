"""WhatsApp conversations linked to citizen records.

A WhatsApp number is tied to the same account as a web sign-in with that mobile number, so the
profile, eligibility and applications are shared between web and WhatsApp. Meta has already
verified that the sender controls the number, so the first message creates the account if needed.
"""

from __future__ import annotations

import logging
import re
import uuid

from agents_core.channels.whatsapp import TEXT_ONLY_REPLY, IncomingMessage, WhatsAppClient
from agents_core.speech import SpeechError, SpeechProvider, language_code, to_wav_16k
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..agent import Agent
from ..auth.otp import normalize_phone
from ..auth.users import upsert_phone_user
from ..auth.whatsapp_login import confirm_login, login_code
from ..db import Citizen, utcnow
from ..errors import BadRequest

log = logging.getLogger(__name__)

UNSUPPORTED_NUMBER = "Sorry, Saathi currently works only with Indian mobile numbers."
DISABLED = "This account has been disabled. / यह खाता बंद कर दिया गया है।"
CONSENT_NOTICE = (
    "Namaste! I am Saathi, a free volunteer helper (not the government). I ask a few questions "
    "(age, work, family income) to find welfare schemes for you. Your answers are used only for this, "
    "and you can say \"delete my data\" at any time. Never send Aadhaar, bank or OTP numbers.\n"
    "Reply YES to continue.\n\n"
    "नमस्ते! मैं साथी हूँ, एक मुफ़्त स्वयंसेवी सहायक (सरकार नहीं)। आपके लिए योजनाएँ ढूँढने के लिए मैं कुछ सवाल "
    "पूछूँगा (उम्र, काम, परिवार की आय)। आपके जवाब सिर्फ़ इसी काम में लिए जाएँगे और आप कभी भी \"मेरा डेटा हटाओ\" "
    "कह सकते हैं। आधार, बैंक या OTP नंबर कभी न भेजें।\nआगे बढ़ने के लिए हाँ लिखें।"
)
WELCOME = (
    "Thank you! Tell me a little about yourself: your age, your work, and which state you live in.\n"
    "धन्यवाद! अपने बारे में थोड़ा बताइए: आपकी उम्र, आपका काम, और आप किस राज्य में रहते हैं।"
)
LOGIN_CONFIRMED = (
    "Done! Go back to the Saathi website: you are now signed in. "
    "If you did not just try to sign in to Saathi, someone may be trying to use your number; do not share codes.\n"
    "हो गया! साथी वेबसाइट पर वापस जाएँ: आप साइन इन हो गए हैं। अगर आपने अभी साइन इन नहीं किया, तो कोई आपके नंबर का "
    "इस्तेमाल करने की कोशिश कर रहा हो सकता है; किसी के साथ कोड साझा न करें।"
)
LOGIN_UNKNOWN = (
    "That sign-in code is wrong or has expired. Please start again on the website.\n"
    "यह साइन-इन कोड गलत है या समाप्त हो गया है। कृपया वेबसाइट पर फिर से शुरू करें।"
)
CHAT_UNAVAILABLE = (
    "Chat is not available right now. Please try again later.\n"
    "बातचीत अभी उपलब्ध नहीं है। कृपया बाद में कोशिश करें।"
)
NOT_HEARD = (
    "Sorry, I could not hear that clearly. Please send the voice note again, or type your message.\n"
    "माफ़ कीजिए, मैं ठीक से सुन नहीं पाया। कृपया दोबारा बोलकर भेजें या लिखकर भेजें।"
)
_YES = re.compile(r"^\s*(yes|y|ok|okay|agree|haan|haa|ha|han|ji|हाँ|हां|हा|जी|ठीक है)\s*[.!]*\s*$", re.IGNORECASE)


def is_consent_reply(text: str | None) -> bool:
    return bool(text and _YES.match(text))


class WhatsAppCitizenHandler:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        agent: Agent | None,
        consent_version: str,
        *,
        speech: SpeechProvider | None = None,
        client: WhatsAppClient | None = None,
        default_language: str = "hi",
        voice_replies: bool = True,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._consent_version = consent_version
        self._speech = speech if client is not None else None  # voice needs the client to fetch media
        self._client = client
        self._default_language = default_language
        self._voice_replies = voice_replies

    async def __call__(self, message: IncomingMessage) -> str | None:
        try:
            phone = normalize_phone(message.sender)
        except BadRequest:
            return UNSUPPORTED_NUMBER

        if (code := login_code(message.text)) is not None:
            async with self._sessionmaker() as db:
                return LOGIN_CONFIRMED if await confirm_login(db, code, phone) else LOGIN_UNKNOWN
        if self._agent is None:
            return CHAT_UNAVAILABLE

        async with self._sessionmaker() as db:
            citizen = await self._citizen_for(db, phone)
            if citizen is None:
                await db.commit()
                return DISABLED
            if citizen.consent_at is None:
                if is_consent_reply(message.text):
                    citizen.consent_version = self._consent_version
                    citizen.consent_at = utcnow()
                    await db.commit()
                    return WELCOME
                await db.commit()
                return CONSENT_NOTICE
            citizen_id = citizen.id
            language = language_code(citizen.language, self._default_language)
            await db.commit()

        if message.text is not None:
            return await self._agent.handle(str(citizen_id), message.text)
        if message.media_id is None or self._speech is None:
            return TEXT_ONLY_REPLY

        transcript = await self._transcribe(message.media_id, language)
        if not transcript:
            return NOT_HEARD
        reply = await self._agent.handle(str(citizen_id), transcript)
        if self._voice_replies:
            await self._speak(message.sender, reply, citizen_id)
        return reply  # the text is always sent too, so it can be re-read later

    async def _transcribe(self, media_id: str, language: str) -> str:
        assert self._speech is not None and self._client is not None
        try:
            audio, _ = await self._client.download_media(media_id)
            return (await self._speech.transcribe(await to_wav_16k(audio), language)).strip()
        except (SpeechError, ValueError):
            log.warning("could not transcribe a voice note (provider=%s)", self._speech.name)
            return ""

    async def _speak(self, to: str, text: str, citizen_id: uuid.UUID) -> None:
        assert self._speech is not None and self._client is not None
        async with self._sessionmaker() as db:
            citizen = await db.get(Citizen, citizen_id)
            language = language_code(citizen.language if citizen else None, self._default_language)
        try:
            audio = await self._speech.synthesize(text, language)
            if audio is not None:
                await self._client.send_audio(to, audio.content, audio.mime_type)
        except Exception:  # a failed voice reply must not lose the text reply
            log.warning("could not send a voice reply (provider=%s)", self._speech.name)

    @staticmethod
    async def _citizen_for(db: AsyncSession, phone: str) -> Citizen | None:
        user = await upsert_phone_user(db, phone)
        if not user.is_active:
            return None
        citizen = await db.scalar(select(Citizen).where(Citizen.user_id == user.id))
        if citizen is None:
            citizen = Citizen(id=uuid.uuid4(), user_id=user.id, display_name=user.display_name or "WhatsApp user")
            db.add(citizen)
            await db.flush()
        return citizen
