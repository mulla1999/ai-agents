"""The only way the agent fetches from the internet.

* hosts must be on an allowlist (connector API hosts plus career-page hosts you add)
* HTTPS only; every redirect hop is re-checked
* hostnames resolving to private, loopback or link-local addresses are refused (SSRF)
* robots.txt is honoured for HTML pages
* per-host minimum interval, timeouts, size cap, bounded retries with backoff on 429/5xx
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
# Whole-board job APIs (Greenhouse, Ashby) return every posting with its description in one response; a big
# employer's board passes 5 MB, so those calls may ask for more, up to this cap.
MAX_BOARD_BYTES = 40 * 1024 * 1024
MAX_REDIRECTS = 3

Resolver = Callable[[str], Awaitable[list[str]]]


class FetchError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class BlockedURL(FetchError):
    pass


async def _system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified)


class SafeFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        allowed_hosts: frozenset[str],
        user_agent: str,
        min_interval: float = 2.0,
        resolver: Resolver | None = None,
        require_https: bool = True,
        max_retries: int = 2,
    ) -> None:
        self.client = client
        self.allowed_hosts = allowed_hosts
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.resolver = resolver or _system_resolver
        self.require_https = require_https
        self.max_retries = max_retries
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def with_hosts(self, extra: set[str]) -> SafeFetcher:
        clone = SafeFetcher(self.client, allowed_hosts=self.allowed_hosts | {h.lower() for h in extra},
                            user_agent=self.user_agent, min_interval=self.min_interval, resolver=self.resolver,
                            require_https=self.require_https, max_retries=self.max_retries)
        clone._last, clone._locks, clone._robots = self._last, self._locks, self._robots
        return clone

    def host_allowed(self, host: str) -> bool:
        host = host.lower()
        return any(host == h or host.endswith("." + h) for h in self.allowed_hosts)

    async def check_url(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != "https" and (self.require_https or parts.scheme != "http"):
            raise BlockedURL(f"only https URLs may be fetched: {url}")
        host = (parts.hostname or "").lower()
        if not host or not self.host_allowed(host):
            raise BlockedURL(f"host {host or '?'} is not on the allowlist")
        try:
            addresses = await self.resolver(host)
        except OSError as exc:
            raise FetchError(f"cannot resolve {host}", retryable=True) from exc
        if not addresses or not all(_is_public(a) for a in addresses):
            raise BlockedURL(f"{host} resolves to a private or reserved address")
        return host

    async def _pace(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last.get(host, 0) + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                response = await self._get(urljoin(origin, "/robots.txt"), accept="text/plain")
                if response.status_code >= 400:
                    parser = None  # no robots.txt: allowed
                else:
                    parser.parse(response.text.splitlines())  # type: ignore[union-attr]
            except FetchError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    async def _get(self, url: str, *, accept: str, params: dict | None = None, headers: dict | None = None,
                   max_bytes: int = MAX_BYTES) -> httpx.Response:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host = await self.check_url(current)
            await self._pace(host)
            try:
                async with self.client.stream("GET", current, params=params, follow_redirects=False,
                                              headers={**(headers or {}), "User-Agent": self.user_agent, "Accept": accept}) as response:
                    if response.is_redirect:
                        current = urljoin(current, response.headers.get("location", ""))
                        params = headers = None  # never forward an API key to a redirect target
                        continue
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            raise FetchError(f"response from {host} is larger than {max_bytes} bytes")
                    # The body is already decompressed, so its encoding headers no longer apply.
                    headers = [(k, v) for k, v in response.headers.multi_items()
                               if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                    return httpx.Response(response.status_code, headers=headers, content=bytes(body),
                                          request=response.request)
            except httpx.TimeoutException as exc:
                raise FetchError(f"timed out fetching {host}", retryable=True) from exc
            except httpx.TransportError as exc:
                raise FetchError(f"network error fetching {host}: {exc.__class__.__name__}", retryable=True) from exc
        raise FetchError("too many redirects")

    async def get(self, url: str, *, params: dict | None = None, accept: str = "application/json",
                  respect_robots: bool = False, headers: dict | None = None, max_bytes: int = MAX_BYTES) -> httpx.Response:
        if respect_robots and not await self.robots_allows(url):
            raise BlockedURL(f"robots.txt disallows fetching {url}")
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._get(url, accept=accept, params=params, headers=headers,
                                           max_bytes=min(max_bytes, MAX_BOARD_BYTES))
            except FetchError as exc:
                if not exc.retryable or attempt == self.max_retries:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_retries:
                    raise FetchError(f"HTTP {response.status_code} from {urlsplit(url).hostname}",
                                     status=response.status_code, retryable=True)
                retry_after = response.headers.get("retry-after", "")
                await asyncio.sleep(min(60.0, float(retry_after)) if retry_after.isdigit() else delay)
                delay *= 2
                continue
            return response
        raise FetchError("unreachable")  # pragma: no cover


    async def post_json(self, url: str, body: dict) -> httpx.Response:
        """POST JSON to an allow-listed API (no redirects followed), with the same checks as GET."""
        host = await self.check_url(url)
        await self._pace(host)
        try:
            response = await self.client.post(url, json=body, follow_redirects=False,
                                              headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise FetchError(f"timed out calling {host}", retryable=True) from exc
        except httpx.TransportError as exc:
            raise FetchError(f"network error calling {host}: {exc.__class__.__name__}", retryable=True) from exc
        if len(response.content) > MAX_BYTES:
            raise FetchError(f"response from {host} is larger than {MAX_BYTES} bytes")
        if response.status_code == 429 or response.status_code >= 500:
            raise FetchError(f"HTTP {response.status_code} from {host}", status=response.status_code, retryable=True)
        return response
