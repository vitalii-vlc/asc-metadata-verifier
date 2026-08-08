"""Tests for markdown/JSON report rendering and exit codes (Task 11)."""

from asc_metadata_verifier.models import DeterministicFinding, GateReport, RubricVerdict
from asc_metadata_verifier.report import exit_code, render_json, render_markdown


def _fail_verdict() -> RubricVerdict:
    return RubricVerdict(
        dimension="placeholder_text",
        verdict="fail",
        severity="high",
        confidence=0.95,
        rationale="The description contains obvious placeholder text.",
        offending_quote="Lorem ipsum TODO",
        guideline_ref="2.3.10",
        suggested_fix="Replace the placeholder copy with real marketing copy.",
        locale="en-US",
        field="description",
    )


def _pass_verdict() -> RubricVerdict:
    return RubricVerdict(
        dimension="misleading_claims",
        verdict="pass",
        severity="low",
        confidence=0.9,
        rationale="No misleading claims found.",
        locale="en-US",
        field="description",
    )


def _finding() -> DeterministicFinding:
    return DeterministicFinding(
        locale="en-US",
        field="support_url",
        kind="malformed_url",
        detail="'notaurl' is not a valid URL",
    )


class TestRenderJson:
    def test_round_trips_through_model_validate_json(self):
        report = GateReport(
            status="BLOCK",
            verdicts=[_fail_verdict(), _pass_verdict()],
            deterministic_findings=[_finding()],
            guidelines_available=True,
        )
        payload = render_json(report)
        rebuilt = GateReport.model_validate_json(payload)
        assert rebuilt == report

    def test_round_trips_with_empty_report(self):
        report = GateReport(
            status="PASS", verdicts=[], deterministic_findings=[], guidelines_available=False
        )
        payload = render_json(report)
        rebuilt = GateReport.model_validate_json(payload)
        assert rebuilt == report


class TestRenderMarkdown:
    def test_shows_overall_status(self):
        report = GateReport(
            status="BLOCK",
            verdicts=[_fail_verdict()],
            deterministic_findings=[],
            guidelines_available=True,
        )
        markdown = render_markdown(report)
        assert "BLOCK" in markdown

    def test_groups_by_locale_and_dimension_and_includes_details(self):
        v = _fail_verdict()
        report = GateReport(
            status="BLOCK", verdicts=[v], deterministic_findings=[], guidelines_available=True
        )
        markdown = render_markdown(report)
        assert v.locale in markdown
        assert v.dimension in markdown
        assert v.offending_quote in markdown
        assert v.guideline_ref in markdown
        assert v.rationale in markdown
        assert v.suggested_fix in markdown

    def test_missing_guideline_ref_renders_placeholder(self):
        v = RubricVerdict(
            dimension="keyword_stuffing",
            verdict="warn",
            severity="medium",
            confidence=0.6,
            rationale="Keywords look repetitive.",
            locale="de-DE",
            field="keywords",
        )
        report = GateReport(
            status="WARN", verdicts=[v], deterministic_findings=[], guidelines_available=True
        )
        markdown = render_markdown(report)
        assert v.locale in markdown
        assert v.dimension in markdown
        assert v.rationale in markdown
        # guideline_ref is None -> some placeholder must render, not "None"
        assert "None" not in markdown

    def test_pass_verdicts_do_not_need_detail_fields(self):
        """Non-pass detail (quote/rationale/fix) shouldn't be required for pass verdicts."""
        report = GateReport(
            status="PASS",
            verdicts=[_pass_verdict()],
            deterministic_findings=[],
            guidelines_available=True,
        )
        markdown = render_markdown(report)
        assert "PASS" in markdown
        assert _pass_verdict().locale in markdown

    def test_includes_deterministic_findings(self):
        f = _finding()
        report = GateReport(
            status="WARN", verdicts=[], deterministic_findings=[f], guidelines_available=True
        )
        markdown = render_markdown(report)
        assert f.locale in markdown
        assert f.field in markdown
        assert f.kind in markdown
        assert f.detail in markdown

    def test_notes_offline_when_guidelines_unavailable(self):
        report = GateReport(
            status="PASS", verdicts=[], deterministic_findings=[], guidelines_available=False
        )
        markdown = render_markdown(report)
        assert "offline" in markdown.lower()

    def test_no_offline_note_when_guidelines_available(self):
        report = GateReport(
            status="PASS", verdicts=[], deterministic_findings=[], guidelines_available=True
        )
        markdown = render_markdown(report)
        assert "offline" not in markdown.lower()

    def test_returns_plain_string_not_rich_console_output(self):
        report = GateReport(
            status="PASS", verdicts=[], deterministic_findings=[], guidelines_available=True
        )
        markdown = render_markdown(report)
        assert isinstance(markdown, str)
        # no ANSI escape codes / rich markup leaking through
        assert "\x1b[" not in markdown


class TestExitCode:
    def test_block_is_nonzero(self):
        report = GateReport(
            status="BLOCK", verdicts=[], deterministic_findings=[], guidelines_available=True
        )
        assert exit_code(report) == 1

    def test_warn_is_zero(self):
        report = GateReport(
            status="WARN", verdicts=[], deterministic_findings=[], guidelines_available=True
        )
        assert exit_code(report) == 0

    def test_pass_is_zero(self):
        report = GateReport(
            status="PASS", verdicts=[], deterministic_findings=[], guidelines_available=True
        )
        assert exit_code(report) == 0
