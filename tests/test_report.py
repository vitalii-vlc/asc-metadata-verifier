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
        assert v.field in markdown
        assert v.offending_quote in markdown
        assert v.guideline_ref in markdown
        assert v.rationale in markdown
        assert v.suggested_fix in markdown

    def test_multi_group_locale_times_dimension_grouping(self):
        """Regression guard: grouping must key on (locale, dimension) TOGETHER.

        A grouping bug that keyed on locale-alone or dimension-alone would
        pass the single-verdict test above undetected. Here: two distinct
        (locale, dimension) pairs plus a THIRD pair shared by two verdicts
        with different fields -> exactly 3 group headers, not 4 (the shared
        pair collapses into one group), and the two verdicts sharing a
        group are distinguishable via their `field`.
        """
        v_en_platform = RubricVerdict(
            dimension="other_platform_mentions",
            verdict="fail",
            severity="high",
            confidence=0.9,
            rationale="Mentions Android.",
            offending_quote="Also on Android",
            locale="en-US",
            field="description",
        )
        v_de_platform = RubricVerdict(
            dimension="other_platform_mentions",
            verdict="fail",
            severity="high",
            confidence=0.9,
            rationale="Erwaehnt Android.",
            offending_quote="Auch auf Android",
            locale="de-DE",
            field="description",
        )
        v_en_keywords_description = RubricVerdict(
            dimension="keyword_stuffing",
            verdict="warn",
            severity="medium",
            confidence=0.7,
            rationale="Repeats keywords in the description.",
            locale="en-US",
            field="description",
        )
        v_en_keywords_field = RubricVerdict(
            dimension="keyword_stuffing",
            verdict="warn",
            severity="medium",
            confidence=0.7,
            rationale="Repeats keywords in the keywords field.",
            locale="en-US",
            field="keywords",
        )
        verdicts = [
            v_en_platform,
            v_de_platform,
            v_en_keywords_description,
            v_en_keywords_field,
        ]
        report = GateReport(
            status="BLOCK", verdicts=verdicts, deterministic_findings=[], guidelines_available=True
        )

        markdown = render_markdown(report)

        # exactly 3 group headers: (en-US, other_platform_mentions),
        # (de-DE, other_platform_mentions), (en-US, keyword_stuffing) --
        # the two en-US/keyword_stuffing verdicts share ONE header.
        assert markdown.count("### en-US / other_platform_mentions") == 1
        assert markdown.count("### de-DE / other_platform_mentions") == 1
        assert markdown.count("### en-US / keyword_stuffing") == 1
        assert markdown.count("###") == 3

        # each header names its own correct locale AND dimension (a
        # locale-only or dimension-only grouping bug would merge these).
        assert "### en-US / other_platform_mentions" in markdown
        assert "### de-DE / other_platform_mentions" in markdown
        assert "### en-US / keyword_stuffing" in markdown
        # the two verdicts sharing (en-US, keyword_stuffing) are
        # distinguishable from each other via their rendered `field`.
        assert "**field:** description" in markdown
        assert "**field:** keywords" in markdown

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

    def test_empty_report_shows_fallback_copy(self):
        """Locks in the exact fallback strings for an all-empty GateReport."""
        report = GateReport(
            status="PASS", verdicts=[], deterministic_findings=[], guidelines_available=True
        )
        markdown = render_markdown(report)
        assert "No rubric verdicts." in markdown
        assert "No deterministic findings." in markdown

    def test_empty_string_fields_render_verbatim_not_as_not_available(self):
        """A legitimate empty string is not the same as an absent (None) value.

        offending_quote/guideline_ref/suggested_fix should only fall back to
        the "n/a" placeholder when they are actually None -- a falsy-but-
        present empty string must render as-is (verified here by asserting
        the placeholder does NOT appear when every optional field is "").
        """
        v = RubricVerdict(
            dimension="placeholder_text",
            verdict="fail",
            severity="high",
            confidence=0.9,
            rationale="rationale text",
            offending_quote="",
            guideline_ref="",
            suggested_fix="",
            locale="en-US",
            field="description",
        )
        report = GateReport(
            status="BLOCK", verdicts=[v], deterministic_findings=[], guidelines_available=True
        )
        markdown = render_markdown(report)
        assert "n/a" not in markdown


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


def test_markdown_shows_panel_deliberation_for_multi_voter_panels():
    from asc_metadata_verifier.models import GateReport, JudgeVote, PanelVerdict, RubricVerdict
    from asc_metadata_verifier.report import render_markdown

    def rv(v):
        return RubricVerdict(dimension="placeholder_text", verdict=v, severity="high",
                             confidence=0.9, rationale="r", locale="en-US", field="description")
    votes = [JudgeVote(judge="a", status="voted", verdict=rv("fail")),
             JudgeVote(judge="b", status="voted", verdict=rv("fail")),
             JudgeVote(judge="c", status="voted", verdict=rv("pass"))]
    panel = PanelVerdict(locale="en-US", dimension="placeholder_text", field="description",
                         votes=votes, consensus=rv("fail"), policy="majority_severe",
                         agreement=2 / 3)
    md = render_markdown(GateReport(status="BLOCK", guidelines_available=True,
                                    verdicts=[rv("fail")], panels=[panel]))
    assert "Panel deliberation" in md
    assert "3 judges" in md and "majority_severe" in md


def test_markdown_omits_panel_section_when_no_multivoter_panels():
    from asc_metadata_verifier.models import GateReport
    from asc_metadata_verifier.report import render_markdown
    assert "Panel deliberation" not in render_markdown(
        GateReport(status="PASS", guidelines_available=True))


class TestComputeDegradation:
    """Fix 1: a jury that degrades at runtime (every judge call fails) must be
    surfaced, not silently swallowed into a green PASS."""

    def test_counts_error_votes_and_empty_tally_units(self):
        from asc_metadata_verifier.models import JudgeVote, PanelVerdict, RubricVerdict
        from asc_metadata_verifier.report import compute_degradation

        def rv(v):
            return RubricVerdict(dimension="d", verdict=v, severity="low", confidence=0.0,
                                 rationale="r", locale="en-US", field="description")

        # panel 1: totally empty-tally -- both judges errored.
        empty_panel = PanelVerdict(
            locale="en-US", dimension="placeholder_text", field="description",
            votes=[JudgeVote(judge="a", status="error", error="revoked key"),
                   JudgeVote(judge="b", status="error", error="revoked key")],
            consensus=rv("pass"), policy="majority_severe", agreement=None,
        )
        # panel 2: healthy -- one voter, no errors.
        healthy_panel = PanelVerdict(
            locale="en-US", dimension="keyword_stuffing", field="description",
            votes=[JudgeVote(judge="a", status="voted", verdict=rv("pass"))],
            consensus=rv("pass"), policy="majority_severe", agreement=1.0,
        )
        error_votes, empty_tally_units = compute_degradation([empty_panel, healthy_panel])
        assert error_votes == 2
        assert empty_tally_units == 1

    def test_zero_for_no_panels(self):
        from asc_metadata_verifier.report import compute_degradation
        assert compute_degradation([]) == (0, 0)


class TestDegradedJuryNote:
    """Fix 1: render_markdown must surface degradation loudly, without
    changing gate semantics (still PASS/exit 0) or healthy-run output."""

    def _rv(self, v="pass", **overrides):
        from asc_metadata_verifier.models import RubricVerdict
        defaults = dict(dimension="placeholder_text", verdict=v, severity="low",
                        confidence=0.0, rationale="No judge produced a verdict for this unit.",
                        locale="en-US", field="description")
        defaults.update(overrides)
        return RubricVerdict(**defaults)

    def test_note_appears_when_every_vote_in_a_panel_errors(self):
        from asc_metadata_verifier.models import GateReport, JudgeVote, PanelVerdict
        from asc_metadata_verifier.report import render_markdown

        panel = PanelVerdict(
            locale="en-US", dimension="placeholder_text", field="description",
            votes=[JudgeVote(judge="a", status="error", error="revoked key"),
                   JudgeVote(judge="b", status="error", error="revoked key")],
            consensus=self._rv(), policy="majority_severe", agreement=None,
        )
        report = GateReport(status="PASS", guidelines_available=True, panels=[panel])
        md = render_markdown(report)

        assert "2 judge call(s) failed" in md
        assert "1 unit(s)" in md
        assert "defaulted to pass" in md
        assert "--format json" in md

    def test_note_omits_error_count_when_empty_tally_has_no_errors(self):
        """An empty-tally unit from abstains only (0 errors) must not claim
        a nonzero "judge call(s) failed" count."""
        from asc_metadata_verifier.models import GateReport, JudgeVote, PanelVerdict
        from asc_metadata_verifier.report import render_markdown

        panel = PanelVerdict(
            locale="en-US", dimension="placeholder_text", field="description",
            votes=[JudgeVote(judge="a", status="abstained"),
                   JudgeVote(judge="b", status="not_applicable")],
            consensus=self._rv(), policy="majority_severe", agreement=None,
        )
        report = GateReport(status="PASS", guidelines_available=True, panels=[panel])
        md = render_markdown(report)

        assert "judge call(s) failed" not in md
        assert "1 unit(s)" in md and "defaulted to pass" in md

    def test_no_degraded_note_for_healthy_multi_voter_report(self):
        """Regression guard: a healthy panel (all judges voted, no errors)
        must render exactly as before -- no degraded note at all."""
        from asc_metadata_verifier.models import GateReport, JudgeVote, PanelVerdict
        from asc_metadata_verifier.report import render_markdown

        votes = [JudgeVote(judge="a", status="voted", verdict=self._rv("fail")),
                 JudgeVote(judge="b", status="voted", verdict=self._rv("fail")),
                 JudgeVote(judge="c", status="voted", verdict=self._rv("pass"))]
        panel = PanelVerdict(locale="en-US", dimension="placeholder_text", field="description",
                             votes=votes, consensus=self._rv("fail"),
                             policy="majority_severe", agreement=2 / 3)
        report = GateReport(status="BLOCK", guidelines_available=True,
                            verdicts=[self._rv("fail")], panels=[panel])
        md = render_markdown(report)

        assert "judge call(s) failed" not in md
        assert "defaulted to pass" not in md
        assert "Note:" not in md or "offline" in md.lower()

    def test_no_degraded_note_when_no_panels_at_all(self):
        from asc_metadata_verifier.models import GateReport
        from asc_metadata_verifier.report import render_markdown

        md = render_markdown(GateReport(status="PASS", guidelines_available=True))
        assert "judge call(s) failed" not in md
        assert "defaulted to pass" not in md


# --- Task 8 (v2 sub-project C): code report rendering ---
from asc_metadata_verifier.models import CodeFinding, CodeReport  # noqa: E402
from asc_metadata_verifier.report import (  # noqa: E402
    render_code_report_json,
    render_code_report_text,
)


def _code_report() -> CodeReport:
    f = CodeFinding(rule_id="uiwebview-usage", category="deprecated-api", severity="high",
                    guideline_ref="2.5.x", file="A.swift", line=1, evidence="UIWebView", detail="d")
    return CodeReport(status="BLOCK", findings=[f], analyzed_files=1, parser_backend="tree-sitter")


def test_render_code_text_shows_anchor_and_guideline():
    out = render_code_report_text(_code_report())
    assert "A.swift:1" in out and "2.5.x" in out and "BLOCK" in out


def test_render_code_json_roundtrips():
    import json
    data = json.loads(render_code_report_json(_code_report()))
    assert data["status"] == "BLOCK" and data["findings"][0]["rule_id"] == "uiwebview-usage"
