"""Tests for deterministic reachability checks (v2 sub-project D, Task 6)."""

from asc_metadata_verifier.models import AppMetadata, LocaleMetadata
from asc_metadata_verifier.pages.checks import collect_page_urls, run_reachability
from asc_metadata_verifier.pages.fetch import FetchedPage


def test_collect_page_urls_dedups_and_types():
    meta = AppMetadata(locales=[
        LocaleMetadata(locale="en-US", privacy_url="https://x/p", support_url="https://x/s"),
        LocaleMetadata(locale="de-DE", privacy_url="https://x/p")])  # dup privacy
    pairs = collect_page_urls(meta)
    assert ("privacy", "https://x/p") in pairs and ("support", "https://x/s") in pairs
    assert len([p for p in pairs if p == ("privacy", "https://x/p")]) == 1


def test_unreachable_privacy_is_high():
    pairs = [("privacy", "https://x/p")]
    fetched = {"https://x/p": FetchedPage(url="https://x/p", ok=False, error="HTTP 404")}
    out = run_reachability(pairs, fetched, has_privacy_url=True)
    hit = [f for f in out if f.rule_id == "page-unreachable"]
    assert len(hit) == 1 and hit[0].severity == "high"


def test_empty_page_is_medium():
    pairs = [("support", "https://x/s")]
    fetched = {"https://x/s": FetchedPage(url="https://x/s", ok=True, final_url="https://x/s",
                                          text="  ")}
    out = run_reachability(pairs, fetched, has_privacy_url=True)
    assert any(f.rule_id == "page-empty" and f.severity == "medium" for f in out)


def test_offsite_redirect_is_low():
    pairs = [("marketing", "https://x/m")]
    fetched = {"https://x/m": FetchedPage(url="https://x/m", ok=True,
                                          final_url="https://parked.example/m",
                                          text="hello world " * 5)}
    out = run_reachability(pairs, fetched, has_privacy_url=True)
    assert any(f.rule_id == "page-offsite-redirect" and f.severity == "low" for f in out)


def test_missing_privacy_url_is_high():
    out = run_reachability([], {}, has_privacy_url=False)
    assert any(f.rule_id == "privacy-policy-missing" and f.severity == "high" for f in out)
