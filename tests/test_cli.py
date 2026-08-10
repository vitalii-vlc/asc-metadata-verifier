"""Tests for the `asc-verify` CLI orchestration (Task 12).

The CLI wires: adapter selection -> ingest -> deterministic checks ->
guidelines -> judge (skipped when no key/model) -> gate -> render -> exit
code. `cli.get_guidelines` and `cli.judge_field` are imported at module level
specifically so tests (and Task 15's e2e) can monkeypatch them directly --
that is how these tests avoid any real network call to developer.apple.com.
"""

import json

import pytest
from typer.testing import CliRunner

from asc_metadata_verifier import cli
from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.models import RubricVerdict

FIXTURE_ROOT = "tests/fixtures/fastlane_clean"

runner = CliRunner()


def _unavailable_guidelines(**_kwargs) -> Guidelines:
    return Guidelines(available=False, text="", sections={}, source="offline")


def _fail_verdict() -> RubricVerdict:
    return RubricVerdict(
        dimension="placeholder_text",
        verdict="fail",
        severity="high",
        confidence=0.95,
        rationale="Contains placeholder text.",
        offending_quote="Lorem ipsum",
        locale="en-US",
        field="description",
    )


class TestNoKeyPath:
    def test_exits_zero_reports_status_and_notes_llm_skipped(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        def _judge_field_not_called(*_args, **_kwargs):
            raise AssertionError("judge_field must not run without a key or injected model")

        monkeypatch.setattr(cli, "judge_field", _judge_field_not_called)

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision"])

        assert result.exit_code == 0, result.output
        assert "PASS" in result.output or "WARN" in result.output
        assert "LLM checks skipped" in result.output


class TestJsonFormat:
    def test_stdout_is_valid_json_with_status(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--format", "json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "status" in payload
        assert payload["status"] in {"PASS", "WARN", "BLOCK"}


class TestDryRun:
    def test_skips_guidelines_and_judge_deterministic_only(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        def _get_guidelines_not_called(*_args, **_kwargs):
            raise AssertionError("get_guidelines must not run in --dry-run")

        def _judge_field_not_called(*_args, **_kwargs):
            raise AssertionError("judge_field must not run in --dry-run")

        monkeypatch.setattr(cli, "get_guidelines", _get_guidelines_not_called)
        monkeypatch.setattr(cli, "judge_field", _judge_field_not_called)

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "PASS" in result.output or "WARN" in result.output


class TestIngestErrorPath:
    def test_nonexistent_fastlane_path_exits_2_with_actionable_message(self):
        result = runner.invoke(cli.app, ["tests/fixtures/does_not_exist_at_all"])

        assert result.exit_code == 2, result.output
        assert "Traceback" not in result.output
        assert result.output.strip() != ""

    def test_no_path_and_no_yaml_exits_2(self):
        result = runner.invoke(cli.app, [])

        assert result.exit_code == 2
        assert "Traceback" not in result.output

    def test_nonexistent_guidelines_override_exits_2_with_actionable_message(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = runner.invoke(
            cli.app,
            [FIXTURE_ROOT, "--guidelines", "tests/fixtures/does_not_exist_guidelines.html"],
        )

        assert result.exit_code == 2, result.output
        assert "Traceback" not in result.output
        assert result.output.strip() != ""
        assert "guidelines" in result.output.lower()
        # The raw FileNotFoundError must never propagate out of the command --
        # it's caught and translated into a clean typer.Exit(code=2).
        assert result.exception is None or isinstance(result.exception, SystemExit)


class TestJudgePath:
    def test_canned_fail_verdict_yields_block_and_exit_1(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-test-key")
        monkeypatch.setattr(
            cli,
            "get_guidelines",
            lambda **_kwargs: Guidelines(
                available=True, text="2.3", sections={"2.3": "2.3"}, source="test"
            ),
        )
        monkeypatch.setattr(cli, "judge_field", lambda *_a, **_k: [_fail_verdict()])

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision"])

        assert result.exit_code == 1, result.output
        assert "BLOCK" in result.output
        assert "LLM checks skipped" not in result.output


class TestVisionWiring:
    """Task 17: the vision judge runs unless --no-vision, gated on key/model."""

    def _patch_common(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-test-key")
        monkeypatch.setattr(
            cli,
            "get_guidelines",
            lambda **_kwargs: Guidelines(
                available=True, text="2.3", sections={"2.3": "2.3"}, source="test"
            ),
        )
        monkeypatch.setattr(cli, "judge_field", lambda *_a, **_k: [])

    def test_vision_judge_called_when_screenshots_present_and_not_no_vision(self, monkeypatch):
        self._patch_common(monkeypatch)
        calls = []

        def spy(screenshots, guidelines, model=None):
            calls.append((screenshots, guidelines, model))
            return []

        monkeypatch.setattr(cli, "judge_screenshots", spy)

        result = runner.invoke(cli.app, [FIXTURE_ROOT])

        assert result.exit_code in {0, 1}, result.output
        assert len(calls) == 1
        screenshots, _guidelines, _model = calls[0]
        assert len(screenshots) > 0

    def test_vision_judge_not_called_with_no_vision_flag(self, monkeypatch):
        self._patch_common(monkeypatch)

        def spy_should_not_run(*_a, **_k):
            raise AssertionError("judge_screenshots must not run with --no-vision")

        monkeypatch.setattr(cli, "judge_screenshots", spy_should_not_run)

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision"])

        assert result.exit_code in {0, 1}, result.output

    def test_vision_judge_verdicts_are_merged_into_the_gate(self, monkeypatch):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(cli, "judge_screenshots", lambda *_a, **_k: [_fail_verdict()])

        result = runner.invoke(cli.app, [FIXTURE_ROOT])

        assert result.exit_code == 1, result.output
        assert "BLOCK" in result.output

    def test_vision_judge_not_called_without_key_or_model(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        def spy_should_not_run(*_a, **_k):
            raise AssertionError("judge_screenshots must not run without a key or model")

        monkeypatch.setattr(cli, "judge_screenshots", spy_should_not_run)

        result = runner.invoke(cli.app, [FIXTURE_ROOT])

        assert result.exit_code == 0, result.output


class TestRunVerifyHelper:
    """Direct tests of the plain-function pipeline, independent of typer."""

    def test_raises_ingest_error_for_bad_fastlane_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        with pytest.raises(IngestError):
            cli.run_verify(path=tmp_path / "does_not_exist", dry_run=True)

    def test_returns_llm_skipped_true_when_dry_run(self, tmp_path):
        (tmp_path / "metadata" / "en-US").mkdir(parents=True)
        (tmp_path / "metadata" / "en-US" / "name.txt").write_text("App")

        outcome = cli.run_verify(path=tmp_path, dry_run=True)

        assert outcome.llm_skipped is True
        assert outcome.report.status in {"PASS", "WARN", "BLOCK"}
        assert outcome.report.verdicts == []
        # `VerifyOutcome` also threads out the ingested `meta` and the
        # `Guidelines` actually used (unavailable, since `--dry-run` never
        # fetches guidelines) -- Task 7's `history --app-id` fix depends on
        # `meta` being available here rather than hidden inside `run_verify`.
        assert outcome.meta.locales[0].app_name == "App"
        assert outcome.guidelines.available is False


class TestJuryPath:
    def _judges_file(self, tmp_path):
        p = tmp_path / "judges.yaml"
        p.write_text(
            "consensus: most_severe\n"
            "judges:\n"
            "  - {name: a, provider: anthropic, model: claude-sonnet-5}\n"
            "  - {name: b, provider: anthropic, model: claude-opus-4-8}\n",
            encoding="utf-8",
        )
        return p

    def test_jury_runs_panel_and_emits_panels_in_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        # Stub build_panel to avoid real models: a panel whose run_panel returns
        # one BLOCK-worthy PanelVerdict.
        from asc_metadata_verifier.models import JudgeVote, PanelVerdict, RubricVerdict

        rv = RubricVerdict(dimension="placeholder_text", verdict="fail", severity="high",
                           confidence=0.9, rationale="r", offending_quote="Lorem",
                           locale="en-US", field="description")

        class StubPanel:
            def run_panel(self, *a, **k):
                return [PanelVerdict(locale="en-US", dimension="placeholder_text",
                                     field="description",
                                     votes=[JudgeVote(judge="a", status="voted", verdict=rv),
                                            JudgeVote(judge="b", status="voted", verdict=rv)],
                                     consensus=rv, policy="most_severe", agreement=1.0)]

        monkeypatch.setattr(cli, "build_panel", lambda *a, **k: StubPanel())

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--judges",
                                         str(self._judges_file(tmp_path)), "--format", "json"])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "BLOCK"
        assert len(payload["panels"]) == 1
        assert payload["panels"][0]["votes"][0]["judge"] == "a"

    def test_all_unavailable_judges_degrades_to_deterministic(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)
        p = tmp_path / "j.yaml"
        p.write_text(
            "judges:\n"
            "  - {name: g, provider: openai, model: gpt-4o, api_key_env: OPENAI_API_KEY}\n",
            encoding="utf-8",
        )
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--judges", str(p)])
        assert result.exit_code == 0, result.output
        assert "LLM checks skipped" in result.output

    def test_consensus_without_judges_is_a_usage_error(self):
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--consensus", "most_severe"])
        assert result.exit_code == 2 and "Traceback" not in result.output

    def test_bad_consensus_name_exits_2_actionably(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)
        p = self._judges_file(tmp_path)
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--judges", str(p), "--consensus", "bogus"])
        assert result.exit_code == 2 and "Traceback" not in result.output

    def test_degraded_jury_run_warns_on_stderr_but_still_exits_0(self, tmp_path, monkeypatch):
        """Fix 1: every judge call failing at runtime must not be a silent
        green PASS -- a WARNING lands on stderr even though the gate still
        conservatively passes (exit 0, no exit-code change)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        from asc_metadata_verifier.models import JudgeVote, PanelVerdict, RubricVerdict

        empty_rv = RubricVerdict(dimension="placeholder_text", verdict="pass", severity="low",
                                 confidence=0.0,
                                 rationale="No judge produced a verdict for this unit.",
                                 locale="en-US", field="description")

        class StubPanel:
            def run_panel(self, *a, **k):
                return [PanelVerdict(
                    locale="en-US", dimension="placeholder_text", field="description",
                    votes=[JudgeVote(judge="a", status="error", error="revoked key"),
                           JudgeVote(judge="b", status="error", error="revoked key")],
                    consensus=empty_rv, policy="most_severe", agreement=None,
                )]

        monkeypatch.setattr(cli, "build_panel", lambda *a, **k: StubPanel())

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--judges",
                                         str(self._judges_file(tmp_path))])

        assert result.exit_code == 0, result.output
        assert "WARNING" in result.output
        assert "judge call(s) failed" in result.output

    def test_healthy_jury_run_has_no_degraded_warning(self, tmp_path, monkeypatch):
        """Regression guard: a healthy jury run must not print the new WARNING."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        from asc_metadata_verifier.models import JudgeVote, PanelVerdict, RubricVerdict

        rv = RubricVerdict(dimension="placeholder_text", verdict="pass", severity="low",
                           confidence=0.9, rationale="r", locale="en-US", field="description")

        class StubPanel:
            def run_panel(self, *a, **k):
                return [PanelVerdict(
                    locale="en-US", dimension="placeholder_text", field="description",
                    votes=[JudgeVote(judge="a", status="voted", verdict=rv),
                           JudgeVote(judge="b", status="voted", verdict=rv)],
                    consensus=rv, policy="most_severe", agreement=1.0,
                )]

        monkeypatch.setattr(cli, "build_panel", lambda *a, **k: StubPanel())

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--judges",
                                         str(self._judges_file(tmp_path))])

        assert result.exit_code == 0, result.output
        assert "WARNING" not in result.output


class TestPersistence:
    """Task 7: the default-command group (bare `verify` keeps working with no
    subcommand token) plus --db/--cache/--save wiring and the history/diff
    subcommands.
    """

    def test_bare_verify_still_works_with_no_subcommand(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision"])  # NO 'verify' token

        assert result.exit_code == 0, result.output

    def test_db_saves_and_history_lists(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        db = f"sqlite:///{tmp_path / 'runs.db'}"
        assert runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--db", db]).exit_code == 0

        out = runner.invoke(cli.app, ["history", "--db", db])

        assert out.exit_code == 0 and ("PASS" in out.output or "WARN" in out.output)

    def test_diff_between_two_saved_runs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-test-key")
        monkeypatch.setattr(
            cli,
            "get_guidelines",
            lambda **_kwargs: Guidelines(
                available=True, text="2.3", sections={"2.3": "2.3"}, source="test"
            ),
        )
        db = f"sqlite:///{tmp_path / 'runs.db'}"

        # First run: a canned fail verdict -> BLOCK.
        monkeypatch.setattr(cli, "judge_field", lambda *_a, **_k: [_fail_verdict()])
        r1 = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--db", db])
        assert r1.exit_code == 1, r1.output

        # Second run: no findings -> PASS. The planted fail is now "resolved".
        monkeypatch.setattr(cli, "judge_field", lambda *_a, **_k: [])
        r2 = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--db", db])
        assert r2.exit_code == 0, r2.output

        hist = runner.invoke(cli.app, ["history", "--db", db, "--format", "json"])
        assert hist.exit_code == 0, hist.output
        runs = json.loads(hist.output)
        assert len(runs) == 2
        # `history` lists newest first: runs[0] is the second (PASS) run,
        # runs[1] is the first (BLOCK) run.
        newer_id, older_id = runs[0]["run_id"], runs[1]["run_id"]

        diff_result = runner.invoke(cli.app, ["diff", older_id, newer_id, "--db", db])

        assert diff_result.exit_code == 0, diff_result.output
        assert "# Run diff: BLOCK ->" in diff_result.output
        assert "## Resolved (1)" in diff_result.output
        assert "placeholder_text" in diff_result.output

    def test_bad_db_scheme_exits_2_no_traceback(self):
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--db", "mysql://h/d", "--dry-run"])

        assert result.exit_code == 2 and "Traceback" not in result.output

    def test_saved_run_has_real_app_id_and_history_filters_by_it(self, tmp_path, monkeypatch):
        """Fix round 1, Important #2: `RunRecord.app_id` must be the actual
        ingested app id (not None), and `history --app-id` must filter on it.
        Uses `tests/fixtures/metadata.yaml`, whose app_id is "123456789"
        (see `tests/test_ingest_yaml.py`).
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        db = f"sqlite:///{tmp_path / 'runs.db'}"
        yaml_fixture = "tests/fixtures/metadata.yaml"

        result = runner.invoke(
            cli.app, ["verify", "--yaml", yaml_fixture, "--no-vision", "--db", db]
        )
        assert result.exit_code in {0, 1}, result.output

        matched = runner.invoke(
            cli.app, ["history", "--db", db, "--app-id", "123456789", "--format", "json"]
        )
        assert matched.exit_code == 0, matched.output
        matched_runs = json.loads(matched.output)
        assert len(matched_runs) == 1
        assert matched_runs[0]["app_id"] == "123456789"

        unmatched = runner.invoke(
            cli.app, ["history", "--db", db, "--app-id", "no-such-app-id", "--format", "json"]
        )
        assert unmatched.exit_code == 0, unmatched.output
        assert json.loads(unmatched.output) == []

    def test_save_failure_warns_but_keeps_report_and_gate_exit_code(self, monkeypatch):
        """Honesty-contract test: report-first-then-save. A `save_run` failure
        must never hide the already-printed report or change the exit code --
        only a stderr WARNING is added.
        """
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-test-key")
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)
        monkeypatch.setattr(cli, "judge_field", lambda *_a, **_k: [_fail_verdict()])

        class _BoomRepo:
            def save_run(self, record):
                raise RuntimeError("disk full")

        monkeypatch.setattr(cli, "resolve_repository", lambda _db: _BoomRepo())

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--db", "sqlite:///unused"])

        # (a) the report was still printed...
        assert "BLOCK" in result.output
        # (b) ...and the exit code is still the gate's own code (unchanged by
        # the persistence failure)...
        assert result.exit_code == 1, result.output
        # (c) ...with a WARNING about the save failure, not a hidden/silent one.
        assert "WARNING: failed to persist run" in result.output
        assert "Traceback" not in result.output
