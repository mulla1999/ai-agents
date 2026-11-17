"""Encryption of user secrets (SMTP passwords, LLM keys) at rest.

The master key comes from ``HIREFINCH_ENCRYPTION_KEYS`` (comma-separated Fernet keys, newest first,
so old keys can be rotated out). Outside production a key is generated once into the private data
directory; in production the setting is required. Secrets are never logged or returned by the API.
"""

from __future__ import annotations

import json
import os
import stat
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretError(RuntimeError):
    pass


def _dev_key(data_dir: Path) -> str:
    path = data_dir / ".encryption_key"
    if path.exists():
        return path.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode()
    path.write_text(key)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return key


@lru_cache(maxsize=4)
def _cipher(keys: str) -> MultiFernet:
    try:
        return MultiFernet([Fernet(k.strip().encode()) for k in keys.split(",") if k.strip()])
    except (ValueError, TypeError) as exc:
        raise SecretError("HIREFINCH_ENCRYPTION_KEYS must be Fernet keys (32 url-safe base64 bytes)") from exc


class SecretBox:
    def __init__(self, keys: str) -> None:
        if not keys.strip():
            raise SecretError("no encryption key configured")
        self._f = _cipher(keys)

    @classmethod
    def from_settings(cls, settings) -> SecretBox:  # noqa: ANN001
        keys = settings.encryption_keys.get_secret_value() if settings.encryption_keys else None
        if not keys:
            if settings.environment == "production":
                raise SecretError("HIREFINCH_ENCRYPTION_KEYS is required in production")
            keys = _dev_key(settings.data_dir)
        return cls(keys)

    def seal(self, values: dict[str, Any]) -> str:
        return self._f.encrypt(json.dumps(values).encode()).decode()

    def open(self, token: str | None) -> dict[str, Any]:
        if not token:
            return {}
        try:
            return json.loads(self._f.decrypt(token.encode()))
        except InvalidToken as exc:
            raise SecretError("a stored secret could not be decrypted (wrong or rotated-out key)") from exc

    def rotate(self, token: str) -> str:
        return self._f.rotate(token.encode()).decode()
