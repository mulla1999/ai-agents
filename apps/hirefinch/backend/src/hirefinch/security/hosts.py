"""Checks for hosts users type in (SMTP servers, LLM endpoints): the server must never be steered
at private networks, cloud metadata addresses or odd ports (SSRF)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

SMTP_PORTS = frozenset({25, 465, 587, 2525})


class UnsafeHost(ValueError):
    pass


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified)


def ensure_public_host(host: str, *, allow_private: bool = False) -> None:
    host = host.strip().lower()
    if not host or len(host) > 253 or any(c in host for c in "/@ \\"):
        raise UnsafeHost("enter a host name such as smtp.gmail.com")
    if allow_private:
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise UnsafeHost(f"cannot resolve {host}") from exc
    if not addresses or not all(_public(a) for a in addresses):
        raise UnsafeHost(f"{host} points to a private or reserved address, which is not allowed")


def ensure_smtp_target(host: str, port: int, *, allow_private: bool = False) -> None:
    if port not in SMTP_PORTS:
        raise UnsafeHost(f"SMTP port must be one of {sorted(SMTP_PORTS)}")
    ensure_public_host(host, allow_private=allow_private)


def ensure_https_endpoint(url: str, *, allow_private: bool = False) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise UnsafeHost("the endpoint must be an https:// URL without credentials")
    ensure_public_host(parts.hostname, allow_private=allow_private)
    return url.strip().rstrip("/")
