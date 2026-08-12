"""Tests for the HTML report page scaffold (v2 sub-project E, Task 2)."""

import re

from asc_metadata_verifier.html_report import render_html
from asc_metadata_verifier.models import CodeFinding, GateReport


def _report():
    return GateReport(status="BLOCK", guidelines_available=True,
                      code_findings=[CodeFinding(rule_id="uiwebview-usage",
                                                 category="deprecated-api", severity="high",
                                                 guideline_ref="2.5.x", file="A.swift", line=42,
                                                 evidence="UIWebView", detail="deprecated")])


def test_page_is_self_contained_and_has_stamp():
    html = render_html(_report(), app_id="123", locale="en-US",
                       generated_at="2026-08-12 09:00 UTC")
    assert "<style>" in html and "<script>" in html
    assert "BLOCK" in html
    assert "fonts.googleapis" not in html and "cdn" not in html.lower()
    assert not re.search(r'(href|src)\s*=\s*["\']https?://', html)


def test_summary_counts_and_context():
    html = render_html(_report(), app_id="123", locale="en-US",
                       generated_at="2026-08-12 09:00 UTC")
    assert "123" in html and "en-US" in html and "2026-08-12 09:00 UTC" in html


def test_render_is_deterministic():
    a = render_html(_report(), generated_at="t")
    b = render_html(_report(), generated_at="t")
    assert a == b


def test_pass_report_renders_clean_no_fix_prompt():
    html = render_html(GateReport(status="PASS", guidelines_available=True))
    assert "PASS" in html and "sev-pass" in html and "gate passed" in html
    assert 'id="fix-all"' not in html  # nothing to fix -> no master prompt
