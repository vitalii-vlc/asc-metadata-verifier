"""Tests for FetchedPage + LocalPageFetcher (v2 sub-project D, Task 3)."""

from asc_metadata_verifier.pages.fetch import LocalPageFetcher


def test_local_fetcher_returns_extracted_text():
    f = LocalPageFetcher({"https://x/p": "<h1>Privacy</h1><p>data</p>"})
    page = f.fetch("https://x/p")
    assert page.ok and "Privacy" in page.text and page.url == "https://x/p"


def test_local_fetcher_unknown_url_is_factual_not_fatal():
    page = LocalPageFetcher({}).fetch("https://x/missing")
    assert page.ok is False and page.text is None and page.error
