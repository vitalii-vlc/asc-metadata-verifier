"""Deterministic reachability checks over fetched pages. Objective, offline-
capable (works on LocalPageFetcher output). No LLM."""

from __future__ import annotations

from urllib.parse import urlparse

from asc_metadata_verifier.models import AppMetadata, PageFinding
from asc_metadata_verifier.pages.fetch import FetchedPage

_FIELDS = (("privacy", "privacy_url"), ("support", "support_url"), ("marketing", "marketing_url"))
_UNREACHABLE_SEV = {"privacy": "high", "support": "high", "marketing": "medium"}
_GUIDELINE = {"privacy": "5.1.1", "support": "5.1.1", "marketing": "2.3.1"}
_EMPTY_MIN_CHARS = 40


def collect_page_urls(meta: AppMetadata) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for lm in meta.locales:
        for page_type, field in _FIELDS:
            url = getattr(lm, field)
            if url and (page_type, url) not in seen:
                seen.add((page_type, url))
                out.append((page_type, url))
    return out


def run_reachability(
    page_urls: list[tuple[str, str]],
    fetched: dict[str, FetchedPage],
    *,
    has_privacy_url: bool,
) -> list[PageFinding]:
    out: list[PageFinding] = []
    if not has_privacy_url:
        out.append(PageFinding(
            page_type="privacy", url="", rule_id="privacy-policy-missing", category="privacy",
            severity="high", guideline_ref="5.1.1", evidence="(no privacy_url declared)",
            detail="No privacy policy URL is declared; App Store requires one (5.1.1).",
            suggested_fix="Add a privacy policy URL in App Store Connect."))
    for page_type, url in page_urls:
        fp = fetched.get(url)
        if fp is None or not fp.ok:
            err = (fp.error if fp else "not fetched") or "unreachable"
            out.append(PageFinding(
                page_type=page_type, url=url, rule_id="page-unreachable", category=page_type,
                severity=_UNREACHABLE_SEV[page_type], guideline_ref=_GUIDELINE[page_type],
                evidence=err, detail=f"{page_type} URL did not load: {err}",
                suggested_fix="Ensure the URL is public and returns a real page."))
            continue
        if fp.text is not None and len(fp.text.strip()) < _EMPTY_MIN_CHARS:
            out.append(PageFinding(
                page_type=page_type, url=url, rule_id="page-empty", category=page_type,
                severity="medium", guideline_ref=_GUIDELINE[page_type],
                evidence="(near-empty page)",
                detail=f"{page_type} URL loaded but has almost no content.",
                suggested_fix="Publish real content at this URL."))
        if fp.final_url and urlparse(fp.final_url).hostname != urlparse(url).hostname:
            out.append(PageFinding(
                page_type=page_type, url=url, rule_id="page-offsite-redirect", category=page_type,
                severity="low", guideline_ref=_GUIDELINE[page_type],
                evidence=fp.final_url, detail=f"{page_type} URL redirects to a different host.",
                suggested_fix="Point the declared URL directly at the final page."))
    return out
