"""Bounded, offline-safe page fetch. `LocalPageFetcher` backs --pages-dir and
tests; `HttpPageFetcher` (Task 4) adds the SSRF-guarded live fetch. Neither ever
raises into the analyzer; failures are factual states, never fabrications."""

from __future__ import annotations

import ipaddress
import socket
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from asc_metadata_verifier.pages.content import html_to_text


class FetchedPage(BaseModel):
    url: str
    final_url: str | None = None
    status: int | None = None
    ok: bool = False
    text: str | None = None
    error: str | None = None


@runtime_checkable
class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...


class LocalPageFetcher:
    """Offline fetcher backed by a {url: html} map (from --pages-dir or tests)."""

    def __init__(self, pages: dict[str, str]):
        self._pages = dict(pages)

    def fetch(self, url: str) -> FetchedPage:
        if url not in self._pages:
            return FetchedPage(url=url, ok=False, error="not in local pages map")
        return FetchedPage(
            url=url, final_url=url, status=200, ok=True, text=html_to_text(self._pages[url])
        )


def _resolve(host: str) -> list[str]:
    """Resolve a hostname to IP strings. Module-level so tests can monkeypatch it."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> refuse
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _host_safe(host: str) -> bool:
    try:
        ipaddress.ip_address(host)  # host is an IP literal -> check directly, no DNS
        return not _ip_blocked(host)
    except ValueError:
        pass
    try:
        ips = _resolve(host)
    except OSError:
        return False
    return bool(ips) and all(not _ip_blocked(ip) for ip in ips)


class HttpPageFetcher:
    """SSRF-guarded, bounded live fetch. http(s) only; refuses private hosts and
    private redirect targets; timeout + streamed size cap; manual redirects."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 10.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
    ):
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    def fetch(self, url: str) -> FetchedPage:
        current = url
        try:
            for _hop in range(self._max_redirects + 1):
                parsed = urlparse(current)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    return FetchedPage(
                        url=url, final_url=current, ok=False,
                        error=f"unsupported/invalid target: {current}",
                    )
                if not _host_safe(parsed.hostname):
                    return FetchedPage(
                        url=url, final_url=current, ok=False,
                        error="blocked host (private/loopback/unresolved)",
                    )
                request = self._client.build_request("GET", current)
                response = self._client.send(request, stream=True, follow_redirects=False)
                try:
                    if response.is_redirect and response.headers.get("location"):
                        current = str(httpx.URL(current).join(response.headers["location"]))
                        continue
                    if response.status_code >= 400:
                        return FetchedPage(
                            url=url, final_url=current, status=response.status_code, ok=False,
                            error=f"HTTP {response.status_code}",
                        )
                    body = b""
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) >= self._max_bytes:
                            break
                    text = html_to_text(body[: self._max_bytes].decode("utf-8", "replace"))
                    return FetchedPage(
                        url=url, final_url=current, status=response.status_code, ok=True, text=text
                    )
                finally:
                    response.close()
            return FetchedPage(url=url, final_url=current, ok=False, error="too many redirects")
        except httpx.HTTPError as exc:
            return FetchedPage(url=url, ok=False, error=str(exc)[:200])

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
