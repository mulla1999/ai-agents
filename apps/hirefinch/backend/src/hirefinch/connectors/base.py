"""Connector contract. A connector turns one source into ``RawJob`` records and nothing else:
no scoring, no state, no side effects beyond read-only HTTP through ``SafeFetcher``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..config import Settings
from ..domain import Preferences, RawJob
from ..net import SafeFetcher


class Support(StrEnum):
    IMPLEMENTED = "implemented"  # works without credentials
    NEEDS_CREDENTIALS = "needs_credentials"  # implemented; inactive until keys are configured
    MANUAL = "manual"  # no permitted automation; paste jobs in yourself
    UNSUPPORTED = "unsupported"


class ConnectorError(RuntimeError):
    """The source failed; ``retryable`` tells the scheduler whether to try again later."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class ConnectorAuthError(ConnectorError):
    """Credentials are missing, expired or rejected. Discovery for this source stops and you are told."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ManualInterventionRequired(ConnectorError):
    """The source wants a CAPTCHA, a login or something else only a person may do."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


@dataclass
class SourceContext:
    settings: Settings
    fetcher: SafeFetcher
    preferences: Preferences
    config: dict[str, Any] = field(default_factory=dict)
    # The user's own keys for this source (decrypted for this run only), e.g. {"app_id", "app_key"}.
    credentials: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    jobs: list[RawJob] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Connector(ABC):
    kind: str
    api_hosts: frozenset[str] = frozenset()

    @abstractmethod
    async def fetch(self, ctx: SourceContext) -> FetchResult: ...

    def configured(self, ctx: SourceContext) -> str | None:
        """None when ready, otherwise a short reason (missing key, nothing configured)."""
        return None
