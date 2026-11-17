"""Domain errors, mapped to HTTP responses by the API layer."""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequest(ServiceError):
    pass


class NotFound(ServiceError):
    status_code = 404
    code = "not_found"


class Conflict(ServiceError):
    status_code = 409
    code = "conflict"


class TooManyRequests(ServiceError):
    status_code = 429
    code = "too_many_requests"


class Unavailable(ServiceError):
    status_code = 503
    code = "unavailable"
