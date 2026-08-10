"""Tests for the code-analyzer data models (v2 sub-project C, Task 1)."""

from asc_metadata_verifier.models import CodeFinding, CodeReport, GateReport


def test_code_finding_defaults():
    f = CodeFinding(
        rule_id="uiwebview-usage",
        category="deprecated-api",
        severity="high",
        guideline_ref="2.5.x",
        file="A.swift",
        line=3,
        evidence="UIWebView()",
        detail="deprecated",
    )
    assert f.source == "static" and f.confidence == 1.0 and f.panel is None


def test_code_report_defaults():
    r = CodeReport(status="PASS")
    assert r.findings == [] and r.analyzed_files == 0 and r.jury_used is False


def test_gate_report_has_code_findings_default():
    r = GateReport(status="PASS", guidelines_available=True)
    assert r.code_findings == []
