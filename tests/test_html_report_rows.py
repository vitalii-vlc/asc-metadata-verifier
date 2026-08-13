"""Tests for the _Row normalizer (v2 sub-project E, Task 1)."""

from asc_metadata_verifier.html_report import _rows_from_report
from asc_metadata_verifier.models import (
    CodeFinding,
    DeterministicFinding,
    GateReport,
    JudgeVote,
    PageFinding,
    PanelVerdict,
    RubricVerdict,
)


def _rv(dimension="other_platform_mentions", verdict="fail", severity="high",
        guideline_ref="2.3.1", field="promotional_text", locale="en-US"):
    return RubricVerdict(dimension=dimension, verdict=verdict, severity=severity,
                         confidence=0.9, rationale="mentions Android",
                         offending_quote="Also on Android", guideline_ref=guideline_ref,
                         suggested_fix="Remove it", locale=locale, field=field)


def test_metadata_prefers_panels_over_verdicts_no_double_count():
    v = _rv()
    panel = PanelVerdict(locale="en-US", dimension="other_platform_mentions",
                         field="promotional_text",
                         votes=[JudgeVote(judge="j", status="voted", verdict=v)],
                         consensus=v, policy="majority_severe", agreement=1.0)
    report = GateReport(status="BLOCK", verdicts=[v], panels=[panel], guidelines_available=True)
    meta_rows = [r for r in _rows_from_report(report) if r.subsystem == "Metadata"]
    assert len(meta_rows) == 1 and meta_rows[0].source == "jury" and meta_rows[0].panel is panel


def test_single_judge_uses_verdicts():
    report = GateReport(status="BLOCK", verdicts=[_rv()], guidelines_available=True)
    rows = _rows_from_report(report)
    assert len(rows) == 1 and rows[0].source == "static" and rows[0].level == "block"


def test_pass_verdicts_excluded():
    report = GateReport(status="PASS", verdicts=[_rv(verdict="pass", severity="low")],
                        guidelines_available=True)
    assert _rows_from_report(report) == []


def test_deterministic_and_code_and_pages_rows():
    report = GateReport(
        status="BLOCK", guidelines_available=True,
        deterministic_findings=[DeterministicFinding(locale="en-US", field="app_name",
                                                     kind="over_limit", detail="too long")],
        code_findings=[CodeFinding(rule_id="uiwebview-usage", category="deprecated-api",
                                   severity="high", guideline_ref="2.5.x", file="A.swift",
                                   line=42, evidence="UIWebView", detail="deprecated")],
        page_findings=[PageFinding(page_type="support", url="https://x/s",
                                   rule_id="page-unreachable", category="support", severity="high",
                                   guideline_ref="5.1.1", evidence="HTTP 404",
                                   detail="did not load")])
    rows = {r.subsystem: r for r in _rows_from_report(report)}
    assert rows["Metadata"].rule_label == "over_limit" and rows["Metadata"].level == "block"
    assert rows["Code"].anchor == "A.swift:42" and rows["Code"].evidence == "UIWebView"
    assert rows["Pages"].anchor == "support · https://x/s" and rows["Pages"].level == "block"
