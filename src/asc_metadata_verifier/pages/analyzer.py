"""Orchestrate the pages analysis: fetch each declared URL once, run
deterministic reachability, and (if a jury is provided) the interpretive +
cross-reference checks. Deterministic ordering. Pure aside from the injected
fetcher/jury."""

from __future__ import annotations

from asc_metadata_verifier.gate import evaluate
from asc_metadata_verifier.models import CodeFinding, PageFinding, PagesReport
from asc_metadata_verifier.pages.checks import collect_page_urls, run_reachability
from asc_metadata_verifier.pages.fetch import FetchedPage
from asc_metadata_verifier.pages.jury import apply_page_jury
from asc_metadata_verifier.pages.profile import build_profile


def analyze_pages(meta, *, fetcher, code_findings: list[CodeFinding] | None = None,
                  jury=None, grounding: str | None = None) -> list[PageFinding]:
    page_urls = collect_page_urls(meta)
    fetched: dict[str, FetchedPage] = {}
    for _page_type, url in page_urls:
        if url not in fetched:
            fetched[url] = fetcher.fetch(url)
    has_privacy = any(lm.privacy_url for lm in meta.locales)
    findings = run_reachability(page_urls, fetched, has_privacy_url=has_privacy)
    if jury is not None:
        pages_by_type: dict[str, FetchedPage] = {}
        for page_type, url in page_urls:
            pages_by_type.setdefault(page_type, fetched[url])
        profile = build_profile(code_findings or [])
        findings += apply_page_jury(pages_by_type, profile, jury=jury, grounding=grounding or "")
    findings.sort(key=lambda f: (f.page_type, f.rule_id, f.url))
    return findings


def build_pages_report(findings: list[PageFinding], pages_checked: int, *,
                       fail_on: str = "fail", jury_used: bool = False) -> PagesReport:
    status = evaluate([], [], fail_on=fail_on, page_findings=findings).status
    return PagesReport(status=status, findings=findings, pages_checked=pages_checked,
                       jury_used=jury_used)
