"""Tests for the HTML report fix prompts (Task 4)."""

from asc_metadata_verifier.html_report import render_html
from asc_metadata_verifier.models import CodeFinding, GateReport, PageFinding


def _report():
    return GateReport(
        status="BLOCK", guidelines_available=True,
        code_findings=[CodeFinding(rule_id="uiwebview-usage", category="deprecated-api",
                                   severity="high", guideline_ref="2.5.x", file="A.swift", line=42,
                                   evidence="UIWebView", detail="deprecated",
                                   suggested_fix="Replace UIWebView with WKWebView")],
        page_findings=[PageFinding(page_type="support", url="https://x/s",
                                   rule_id="page-unreachable",
                                   category="support", severity="high", guideline_ref="5.1.1",
                                   evidence="HTTP 404", detail="did not load",
                                   suggested_fix="Publish a live support page")])


def test_section_prompt_has_real_fields():
    html = render_html(_report())
    assert "[BLOCK] uiwebview-usage" in html and "2.5.x" in html and "A.swift:42" in html
    assert "Replace UIWebView with WKWebView" in html


def test_master_prompt_aggregates_and_anchors():
    html = render_html(_report())
    assert 'id="fix-all"' in html and 'href="#fix-all"' in html
    assert html.count("uiwebview-usage") >= 2 and "page-unreachable" in html


def test_prompt_uses_detail_when_no_suggested_fix():
    r = GateReport(status="WARN", guidelines_available=True,
                   code_findings=[CodeFinding(rule_id="insecure-http-endpoint",
                                              category="security-ats", severity="low",
                                              guideline_ref="2.5.2", file="B.swift", line=3,
                                              evidence="http://x", detail="insecure http endpoint",
                                              suggested_fix=None)])
    html = render_html(r)
    assert "insecure http endpoint" in html  # falls back to detail
