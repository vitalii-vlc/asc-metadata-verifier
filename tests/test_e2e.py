"""Task 15: end-to-end flawed-app -> BLOCK test (Phase 1 capstone).

Runs the full CLI pipeline (ingest -> deterministic checks -> guidelines ->
judge -> gate -> render -> exit code) against a deliberately-flawed fastlane
fixture (`tests/fixtures/fastlane_flawed/`) that plants FOUR distinct issues,
each hitting a different detection path:

  1. over-limit `app_name`      -> deterministic `over_limit`
  2. placeholder text           -> deterministic `placeholder`
  3. other-platform mention     -> judge dimension `other_platform_mentions`
  4. price in the description   -> judge dimension `price_terms_in_description`

Fully offline: no network, no real Anthropic key. `cli.get_guidelines` is
monkeypatched to an unavailable `Guidelines` (never fetches
developer.apple.com), and `cli.judge_field` is monkeypatched to a fake that
returns two canned `RubricVerdict` fails for issues 3-4 -- these are the same
seams `tests/test_cli.py` uses, per the module-level-import design in
`cli.py` (see its module docstring).
"""

import json

from typer.testing import CliRunner

from asc_metadata_verifier import cli
from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.models import RubricVerdict

FIXTURE_ROOT = "tests/fixtures/fastlane_flawed"

runner = CliRunner()


def _unavailable_guidelines(**_kwargs) -> Guidelines:
    return Guidelines(available=False, text="", sections={}, source="")


def _fake_judge(meta, guidelines, dimensions, model=None) -> list[RubricVerdict]:
    """Stand in for `judge_field`: two canned fails for the two judge-only
    planted issues (the other two planted issues are caught deterministically
    and never reach the judge). Ignores its inputs -- this is a fixed stub,
    not a rules engine -- exactly like the fakes in `test_cli.py`.
    """
    del meta, guidelines, dimensions, model
    return [
        RubricVerdict(
            dimension="other_platform_mentions",
            verdict="fail",
            severity="high",
            confidence=0.95,
            rationale="Promotional text references Android and Google Play.",
            offending_quote="Also available on Android and Google Play!",
            guideline_ref=None,
            suggested_fix="Remove references to Android/Google Play",
            locale="en-US",
            field="promotional_text",
        ),
        RubricVerdict(
            dimension="price_terms_in_description",
            verdict="fail",
            severity="high",
            confidence=0.9,
            rationale="Description embeds a discounted price for Premium.",
            offending_quote="only $2.99 this week",
            guideline_ref=None,
            suggested_fix="Move pricing out of the description",
            locale="en-US",
            field="description",
        ),
    ]


def _patch_offline_judge(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-e2e")
    monkeypatch.setattr(cli, "get_guidelines", lambda *a, **k: _unavailable_guidelines())
    monkeypatch.setattr(cli, "judge_field", _fake_judge)


class TestFlawedAppMarkdown:
    def test_blocks_and_names_all_four_planted_issues(self, monkeypatch):
        _patch_offline_judge(monkeypatch)

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision"])

        assert result.exit_code == 1, result.output
        assert "BLOCK" in result.output

        # 1. over-limit app_name (deterministic).
        assert "over_limit" in result.output
        assert "app_name" in result.output

        # 2. placeholder text (deterministic).
        assert "placeholder" in result.output

        # 3. other-platform mention (judge).
        assert "other_platform_mentions" in result.output
        assert "Remove references to Android/Google Play" in result.output

        # 4. price in description (judge).
        assert "price_terms_in_description" in result.output
        assert "Move pricing out of the description" in result.output


class TestFlawedAppJson:
    def test_json_status_block_and_planted_items_present(self, monkeypatch):
        _patch_offline_judge(monkeypatch)

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--format", "json"])

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)

        assert payload["status"] == "BLOCK"

        finding_kinds = {f["kind"] for f in payload["deterministic_findings"]}
        assert "over_limit" in finding_kinds
        assert "placeholder" in finding_kinds
        over_limit_fields = {
            f["field"] for f in payload["deterministic_findings"] if f["kind"] == "over_limit"
        }
        assert "app_name" in over_limit_fields

        verdict_dimensions = {v["dimension"] for v in payload["verdicts"]}
        assert "other_platform_mentions" in verdict_dimensions
        assert "price_terms_in_description" in verdict_dimensions

        fixes = {v["suggested_fix"] for v in payload["verdicts"]}
        assert "Remove references to Android/Google Play" in fixes
        assert "Move pricing out of the description" in fixes
