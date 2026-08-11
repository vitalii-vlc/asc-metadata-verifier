"""Tests for gate aggregation logic (Task 11).

`gate.evaluate` classifies every RubricVerdict / DeterministicFinding into a
BLOCK-worthy / WARN-worthy / none outcome, then rolls those up into an
overall GateReport.status per `fail_on`.
"""

from asc_metadata_verifier.gate import evaluate
from asc_metadata_verifier.models import DeterministicFinding, RubricVerdict
from asc_metadata_verifier.report import exit_code


def _verdict(
    verdict: str, severity: str = "low", dimension: str = "placeholder_text"
) -> RubricVerdict:
    return RubricVerdict(
        dimension=dimension,
        verdict=verdict,
        severity=severity,
        confidence=0.9,
        rationale="rationale",
        locale="en-US",
        field="description",
    )


def _finding(kind: str) -> DeterministicFinding:
    return DeterministicFinding(
        locale="en-US",
        field="description",
        kind=kind,
        detail="detail",
    )


class TestVerdictClassification:
    def test_high_severity_fail_blocks(self):
        verdicts = [_verdict("fail", severity="high")]
        report = evaluate(verdicts, [])
        assert report.status == "BLOCK"
        assert exit_code(report) == 1

    def test_only_warns_yield_warn_status(self):
        verdicts = [_verdict("warn", severity="medium")]
        report = evaluate(verdicts, [])
        assert report.status == "WARN"
        assert exit_code(report) == 0

    def test_fail_on_warn_turns_lone_warn_into_block(self):
        verdicts = [_verdict("warn", severity="low")]
        report = evaluate(verdicts, [], fail_on="warn")
        assert report.status == "BLOCK"
        assert exit_code(report) == 1

    def test_medium_severity_fail_is_warn_not_block_under_default_fail_on(self):
        """Pins the exact rule: only HIGH-severity fails block by default."""
        verdicts = [_verdict("fail", severity="medium")]
        report = evaluate(verdicts, [])
        assert report.status == "WARN"

    def test_low_severity_fail_is_warn_not_block_under_default_fail_on(self):
        verdicts = [_verdict("fail", severity="low")]
        report = evaluate(verdicts, [])
        assert report.status == "WARN"

    def test_all_pass_verdicts_yield_pass(self):
        verdicts = [_verdict("pass", severity="low")]
        report = evaluate(verdicts, [])
        assert report.status == "PASS"
        assert exit_code(report) == 0


class TestDeterministicFindingClassification:
    def test_over_limit_alone_blocks(self):
        report = evaluate([], [_finding("over_limit")])
        assert report.status == "BLOCK"

    def test_missing_required_alone_blocks(self):
        report = evaluate([], [_finding("missing_required")])
        assert report.status == "BLOCK"

    def test_placeholder_alone_warns(self):
        report = evaluate([], [_finding("placeholder")])
        assert report.status == "WARN"

    def test_malformed_url_alone_warns(self):
        report = evaluate([], [_finding("malformed_url")])
        assert report.status == "WARN"

    def test_fail_on_warn_turns_placeholder_into_block(self):
        report = evaluate([], [_finding("placeholder")], fail_on="warn")
        assert report.status == "BLOCK"


class TestEmptyInputs:
    def test_no_verdicts_no_findings_is_pass(self):
        report = evaluate([], [])
        assert report.status == "PASS"


class TestGuidelinesAvailableField:
    def test_defaults_true(self):
        report = evaluate([], [])
        assert report.guidelines_available is True

    def test_can_be_set_false(self):
        report = evaluate([], [], guidelines_available=False)
        assert report.guidelines_available is False


class TestReportContents:
    def test_report_carries_through_inputs(self):
        verdicts = [_verdict("pass")]
        findings = [_finding("placeholder")]
        report = evaluate(verdicts, findings)
        assert report.verdicts == verdicts
        assert report.deterministic_findings == findings


def test_evaluate_passes_panels_through_without_changing_status():
    from asc_metadata_verifier.gate import evaluate
    from asc_metadata_verifier.models import JudgeVote, PanelVerdict, RubricVerdict

    rv = RubricVerdict(dimension="placeholder_text", verdict="warn", severity="medium",
                       confidence=0.7, rationale="r", locale="en-US", field="description")
    panel = PanelVerdict(locale="en-US", dimension="placeholder_text", field="description",
                         votes=[JudgeVote(judge="a", status="voted", verdict=rv)],
                         consensus=rv, policy="majority_severe", agreement=1.0)
    report = evaluate([rv], [], panels=[panel])
    assert report.status == "WARN" and len(report.panels) == 1
    assert evaluate([rv], []).panels == []      # default stays empty


# --- Task 1 (v2 sub-project C): code findings fold into the gate ---
from asc_metadata_verifier.models import CodeFinding  # noqa: E402


def _cf(sev: str) -> CodeFinding:
    return CodeFinding(
        rule_id="r",
        category="c",
        severity=sev,
        guideline_ref="2.5",
        file="A.swift",
        line=1,
        evidence="e",
        detail="d",
    )


def test_high_code_finding_blocks():
    r = evaluate([], [], code_findings=[_cf("high")])
    assert r.status == "BLOCK" and len(r.code_findings) == 1


def test_medium_code_finding_warns():
    assert evaluate([], [], code_findings=[_cf("medium")]).status == "WARN"


def test_low_code_finding_warns():
    assert evaluate([], [], code_findings=[_cf("low")]).status == "WARN"


def test_code_findings_absent_is_unchanged():
    assert evaluate([], []).status == "PASS"


# --- Task 1 (v2 sub-project D): page findings fold into the gate ---
from asc_metadata_verifier.models import PageFinding  # noqa: E402


def _pf(sev: str) -> PageFinding:
    return PageFinding(page_type="privacy", url="https://x", rule_id="r", category="privacy",
                       severity=sev, guideline_ref="5.1.1", evidence="e", detail="d")


def test_high_page_finding_blocks():
    r = evaluate([], [], page_findings=[_pf("high")])
    assert r.status == "BLOCK" and len(r.page_findings) == 1


def test_medium_page_finding_warns():
    assert evaluate([], [], page_findings=[_pf("medium")]).status == "WARN"


def test_page_findings_absent_is_unchanged():
    assert evaluate([], []).status == "PASS"
