"""Tests for HTML finding cards / evidence / jury panels (Task 3)."""

from asc_metadata_verifier.html_report import render_html
from asc_metadata_verifier.models import (
    CodeFinding,
    DeterministicFinding,
    GateReport,
    JudgeVote,
    PanelVerdict,
    RubricVerdict,
)


def _code(**kw):
    base = dict(rule_id="uiwebview-usage", category="deprecated-api", severity="high",
                guideline_ref="2.5.x", file="A.swift", line=42, evidence="UIWebView",
                detail="deprecated since 2020", suggested_fix="Use WKWebView")
    base.update(kw)
    return CodeFinding(**base)


def _report(**kw):
    return GateReport(status="BLOCK", guidelines_available=True, **kw)


def test_finding_renders_rule_guideline_anchor():
    html = render_html(_report(code_findings=[_code()]))
    assert "uiwebview-usage" in html and "2.5.x" in html
    assert "A.swift:42" in html and "WKWebView" in html


def test_evidence_is_escaped():
    html = render_html(_report(code_findings=[_code(evidence="<script>alert(1)</script>")]))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)" not in html


def test_evidence_only_no_fabricated_addition_line():
    html = render_html(_report(code_findings=[_code()]))
    assert 'class="row add"' not in html


def test_none_guideline_renders_na():
    # deterministic findings carry no guideline_ref -> the pill must read n/a
    html = render_html(_report(deterministic_findings=[
        DeterministicFinding(locale="en-US", field="app_name", kind="over_limit",
                             detail="too long")]))
    assert "n/a" in html


def test_jury_panel_shows_votes():
    v = RubricVerdict(dimension="other_platform_mentions", verdict="fail", severity="high",
                      confidence=0.9, rationale="r", guideline_ref="2.3.1", locale="en-US",
                      field="promotional_text")
    panel = PanelVerdict(locale="en-US", dimension="other_platform_mentions",
                         field="promotional_text",
                         votes=[JudgeVote(judge="claude-haiku", status="voted", verdict=v)],
                         consensus=v, policy="majority_severe", agreement=1.0)
    html = render_html(_report(verdicts=[v], panels=[panel]))
    assert "claude-haiku" in html and "majority_severe" in html and "consensus" in html
