"""Sending OTP text messages."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from ..config import Settings

log = logging.getLogger(__name__)


class SmsSender(Protocol):
    async def send(self, phone_e164: str, text: str) -> None: ...


class ConsoleSmsSender:
    """Development only: writes the message to the log instead of sending it. Refused in production."""

    async def send(self, phone_e164: str, text: str) -> None:
        log.warning("[DEV SMS to %s] %s", phone_e164, text)


class TwilioSmsSender:
    """Twilio Messaging API. Commercial SMS to Indian numbers also needs DLT sender/template registration."""

    def __init__(self, *, account_sid: str, auth_token: str, from_number: str, http: httpx.AsyncClient) -> None:
        self._url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        self._auth = (account_sid, auth_token)
        self._from = from_number
        self._http = http

    async def send(self, phone_e164: str, text: str) -> None:
        response = await self._http.post(
            self._url, auth=self._auth, data={"From": self._from, "To": phone_e164, "Body": text}
        )
        response.raise_for_status()


def build_sms_sender(settings: Settings, http: httpx.AsyncClient) -> SmsSender:
    if settings.sms_provider == "twilio":
        if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
            raise ValueError("SAATHI_TWILIO_ACCOUNT_SID, _AUTH_TOKEN and _FROM_NUMBER are required for Twilio")
        return TwilioSmsSender(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token.get_secret_value(),
            from_number=settings.twilio_from_number,
            http=http,
        )
    return ConsoleSmsSender()
