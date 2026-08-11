"""Tests for the SSRF-guarded HttpPageFetcher (v2 sub-project D, Task 4).

Fully offline: httpx.MockTransport + a monkeypatched `_resolve`."""

import httpx

from asc_metadata_verifier.pages import fetch as fetch_mod
from asc_metadata_verifier.pages.fetch import HttpPageFetcher


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_handler(request):
    return httpx.Response(200, html="<h1>Privacy</h1><p>We collect email.</p>")


def test_fetches_and_extracts_when_host_public(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["93.184.216.34"])  # public
    f = HttpPageFetcher(client=_client(_ok_handler))
    page = f.fetch("https://example.com/privacy")
    assert page.ok and "We collect email." in page.text and page.status == 200


def test_refuses_loopback_ip_literal_without_network():
    f = HttpPageFetcher(client=_client(_ok_handler))
    page = f.fetch("http://127.0.0.1/admin")
    assert page.ok is False and "block" in (page.error or "").lower()


def test_refuses_private_hostname(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["10.0.0.5"])
    f = HttpPageFetcher(client=_client(_ok_handler))
    page = f.fetch("https://internal.example.com/")
    assert page.ok is False and "block" in (page.error or "").lower()


def test_refuses_redirect_to_private(monkeypatch):
    monkeypatch.setattr(
        fetch_mod, "_resolve",
        lambda host: ["93.184.216.34"] if host == "example.com" else ["127.0.0.1"],
    )

    def redir_handler(request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, text="secret")

    f = HttpPageFetcher(client=_client(redir_handler))
    page = f.fetch("https://example.com/start")
    assert page.ok is False


def test_caps_response_size(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["93.184.216.34"])
    big = "<p>" + ("A" * 5000) + "</p>"

    def big_handler(request):
        return httpx.Response(200, html=big)

    f = HttpPageFetcher(client=_client(big_handler), max_bytes=1000)
    page = f.fetch("https://example.com/big")
    assert page.ok and len(page.text) <= 1000


def test_http_error_becomes_factual_error(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["93.184.216.34"])

    def boom_handler(request):
        raise httpx.ConnectError("boom")

    f = HttpPageFetcher(client=_client(boom_handler))
    page = f.fetch("https://example.com/x")
    assert page.ok is False and page.error
