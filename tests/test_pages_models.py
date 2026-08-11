"""Tests for the pages-analyzer data models (v2 sub-project D, Task 1)."""

from asc_metadata_verifier.models import GateReport, PageFinding, PagesReport


def test_page_finding_defaults():
    f = PageFinding(
        page_type="privacy",
        url="https://x/p",
        rule_id="page-unreachable",
        category="privacy",
        severity="high",
        guideline_ref="5.1.1",
        evidence="HTTP 404",
        detail="did not load",
    )
    assert f.source == "static" and f.confidence == 1.0 and f.panel is None


def test_pages_report_defaults():
    r = PagesReport(status="PASS")
    assert r.findings == [] and r.pages_checked == 0 and r.jury_used is False


def test_gate_report_has_page_findings_default():
    assert GateReport(status="PASS", guidelines_available=True).page_findings == []
