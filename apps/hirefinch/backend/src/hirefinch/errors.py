"""Errors that map to an HTTP response with a stable code and a message safe to show."""

from __future__ import annotations


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
