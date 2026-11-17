"""Load scheme records from ``*.yaml`` files."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import Scheme


class SchemeDataError(ValueError):
    """A scheme file is missing, malformed or duplicated."""


def load_schemes(directory: Path) -> list[Scheme]:
    if not directory.is_dir():
        raise SchemeDataError(f"scheme directory not found: {directory}")

    schemes: list[Scheme] = []
    seen: dict[str, Path] = {}
    for path in sorted(directory.rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        try:
            scheme = Scheme.model_validate(raw)
        except ValidationError as exc:
            raise SchemeDataError(f"{path}: {exc}") from exc
        if scheme.id in seen:
            raise SchemeDataError(f"{path}: duplicate scheme id {scheme.id!r} (also in {seen[scheme.id]})")
        seen[scheme.id] = path
        schemes.append(scheme)

    if not schemes:
        raise SchemeDataError(f"no scheme files found in {directory}")
    return schemes
