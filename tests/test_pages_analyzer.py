"""Tests for the pages analyzer orchestrator (v2 sub-project D, Task 8). Offline
via LocalPageFetcher."""

from asc_metadata_verifier.models import AppMetadata, LocaleMetadata
from asc_metadata_verifier.pages.analyzer import analyze_pages, build_pages_report
from asc_metadata_verifier.pages.fetch import LocalPageFetcher


def _meta():
    return AppMetadata(locales=[LocaleMetadata(locale="en-US",
        privacy_url="https://x/p", support_url="https://x/s")])


def test_analyze_flags_unreachable_support_offline():
    fetcher = LocalPageFetcher({"https://x/p": "<p>We collect your email address here.</p>"})
    findings = analyze_pages(_meta(), fetcher=fetcher)  # support URL not in map -> unreachable
    assert any(f.rule_id == "page-unreachable" and f.page_type == "support" for f in findings)


def test_build_pages_report_status_from_severity():
    fetcher = LocalPageFetcher({})  # both unreachable (privacy/support are high)
    findings = analyze_pages(_meta(), fetcher=fetcher)
    rep = build_pages_report(findings, pages_checked=2)
    assert rep.status == "BLOCK" and rep.pages_checked == 2


def test_deterministic_ordering():
    fetcher = LocalPageFetcher({})
    a = analyze_pages(_meta(), fetcher=fetcher)
    b = analyze_pages(_meta(), fetcher=fetcher)
    key = lambda f: (f.page_type, f.rule_id, f.url)  # noqa: E731
    assert [key(f) for f in a] == [key(f) for f in b]
