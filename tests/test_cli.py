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

        report, llm_skipped = cli.run_verify(path=tmp_path, dry_run=True)

        assert llm_skipped is True
        assert report.status in {"PASS", "WARN", "BLOCK"}
        assert report.verdicts == []
