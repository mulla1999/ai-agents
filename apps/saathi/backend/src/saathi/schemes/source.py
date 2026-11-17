"""Where the agent gets the current list of active schemes from."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .models import Scheme


class SchemeSource(Protocol):
    async def active(self) -> Sequence[Scheme]: ...


class StaticSchemeSource:
    """A fixed list, e.g. loaded from YAML for the CLI and WhatsApp-only deployments."""

    def __init__(self, schemes: Sequence[Scheme]) -> None:
        self._schemes = list(schemes)

    async def active(self) -> Sequence[Scheme]:
        return self._schemes
