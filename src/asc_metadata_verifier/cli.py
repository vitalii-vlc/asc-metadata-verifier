"""`asc-verify`: the CLI that orchestrates the full verification pipeline.

Pipeline: pick an ingest adapter -> `load()` -> deterministic checks ->
guidelines fetch -> text judge + vision judge (both skipped when no
key/model is available; vision additionally skipped by `--no-vision` or when
there are no screenshots) -> gate -> render -> exit code.

The pipeline logic lives in `run_verify`, a plain function with no typer/click
dependency, so it can be called and tested directly. The `verify` typer
command is a thin wrapper: arg parsing, printing, and exit-code translation.

Every collaborator is imported at module level (not inside functions) so
tests -- and Task 15's flawed-app e2e -- can monkeypatch them directly on
this module (e.g. `monkeypatch.setattr(cli, "judge_field", fake)` or
`monkeypatch.setattr(cli, "judge_screenshots", fake)`), which is also how
tests avoid a real network call to the live guidelines source.
"""

from __future__ import annotations

import os
import uuid
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from asc_metadata_verifier.checks.deterministic import run_deterministic
from asc_metadata_verifier.gate import evaluate
from asc_metadata_verifier.guidelines.source import Guidelines, get_guidelines
from asc_metadata_verifier.ingest.asc_api import AscApiAdapter
from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.ingest.fastlane import FastlaneAdapter
from asc_metadata_verifier.ingest.yaml_source import YamlAdapter
from asc_metadata_verifier.judge.agent import judge_field
from asc_metadata_verifier.judge.config import (
    JudgeConfigError,
    JudgeSet,
    judges_from_cli,
    load_judges,
    merge_specs,
)
from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES
from asc_metadata_verifier.judge.panel import build_panel
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.judge.vision import VISION_DIMENSIONS, judge_screenshots
from asc_metadata_verifier.observability import configure_logfire, span
from asc_metadata_verifier.report import (
    compute_degradation,
    exit_code,
    render_json,
    render_markdown,
)

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from asc_metadata_verifier.models import GateReport, PanelVerdict

app = typer.Typer(add_completion=False, no_args_is_help=False)


class OutputFormat(StrEnum):
    md = "md"
    json = "json"


class FailOn(StrEnum):
    warn = "warn"
    fail = "fail"


def _build_judge_set(
    judges_path: str | Path | None,
    judge_cli: list[str] | None,
    consensus_override: str | None,
) -> JudgeSet:
    """Resolve a `JudgeSet` from `--judges`/`--judge`/`--consensus`.

    File specs (if any) are loaded first via `load_judges`; CLI `--judge`
    mini-syntax specs are then merged in on top (CLI overrides a file entry
    of the same name, unmatched CLI specs are appended). A `--consensus`
    override, if given, wins over the file's `consensus` (or the default
    policy when there is no file at all). Raises `JudgeConfigError` for an
    empty resulting spec list or an unrecognized consensus policy name --
    both are actionable usage errors, not tracebacks.
    """
    if judges_path is not None:
        judge_set = load_judges(judges_path)
        specs, consensus = judge_set.specs, judge_set.consensus
    else:
        specs, consensus = [], DEFAULT_POLICY

    if judge_cli:
        specs = merge_specs(specs, judges_from_cli(judge_cli))

    if consensus_override is not None:
        consensus = consensus_override

    if not specs:
        raise JudgeConfigError("No judges configured -- provide --judges and/or --judge.")

    if consensus not in POLICIES:
        raise JudgeConfigError(
            f"Unknown consensus policy {consensus!r}; must be one of {sorted(POLICIES)}"
        )

    return JudgeSet(specs=specs, consensus=consensus)


def run_verify(
    *,
    path: str | Path | None = None,
    yaml_path: str | Path | None = None,
    asc_api_app_id: str | None = None,
    asc_api_key_id: str | None = None,
    asc_api_issuer_id: str | None = None,
    asc_api_key: str | Path | None = None,
    no_vision: bool = False,
    fail_on: str = "fail",
    guidelines_path: str | Path | None = None,
    dry_run: bool = False,
    judge_model: Model | str | None = None,
    judges_path: str | Path | None = None,
    judge_cli: list[str] | None = None,
    consensus: str | None = None,
    max_concurrency: int = 8,
) -> tuple[GateReport, bool]:
    """Run the full verification pipeline; return `(report, llm_skipped)`.

    Adapter selection precedence:
      1. All four `--asc-api-*` values given -> `AscApiAdapter` (live App
         Store Connect API fetch).
      2. Else `yaml_path` given -> `YamlAdapter`.
      3. Else `path` given -> `FastlaneAdapter`.
      4. Else -> `typer.BadParameter` (a usage error typer/click renders as
         an actionable message with exit code 2, without a traceback).

    If *some but not all* of the four `--asc-api-*` values are given, that is
    also a `typer.BadParameter` -- a partial ASC API credential set can never
    produce a working adapter, so it is rejected rather than silently falling
    back to fastlane/YAML.

    In `dry_run` mode, guidelines are never fetched and neither judge runs --
    deterministic checks + gate only, so the command works fully offline with
    no network and no API key. Outside `dry_run`, the text judge runs when
    `judge_model` is injected or `ANTHROPIC_API_KEY` is set in the
    environment; otherwise both judges are skipped and `llm_skipped` is True,
    but the deterministic report + gate + exit code are still produced. The
    vision judge (Task 17) additionally requires `not no_vision` and at least
    one screenshot in the ingested metadata; when it runs, its verdicts are
    appended alongside the text judge's in the same list passed to `evaluate`.

    A jury (multi-LLM panel) is used instead of the single-judge path
    whenever `judges_path` and/or `judge_cli` is given (`jury_requested`).
    `--consensus` without either is a `typer.BadParameter` -- there is no
    jury for it to apply to. When a jury is requested, `_build_judge_set`
    resolves the merged spec list + consensus policy and `build_panel`
    builds the panel; if every judge is unavailable (no key/model), that
    degrades to the same deterministic-only `llm_skipped=True` outcome as
    the no-key v1 path. Otherwise the panel's per-unit consensus verdicts
    populate `verdicts` (for the gate) and the full per-judge panel votes are
    returned in the report's `panels` for the report to render.
    """
    jury_requested = bool(judges_path or judge_cli)
    if consensus is not None and not jury_requested:
        raise typer.BadParameter(
            "--consensus requires --judges and/or --judge -- there is no jury to "
            "reach consensus over otherwise."
        )

    configure_logfire()
    with span("verify"):
        asc_api_fields = {
            "--asc-api-app-id": asc_api_app_id,
            "--asc-api-key-id": asc_api_key_id,
            "--asc-api-issuer-id": asc_api_issuer_id,
            "--asc-api-key": asc_api_key,
        }
        given = {name: value for name, value in asc_api_fields.items() if value is not None}

        if given and len(given) < len(asc_api_fields):
            missing = ", ".join(name for name in asc_api_fields if name not in given)
            raise typer.BadParameter(
                "Partial App Store Connect API credentials given -- "
                f"missing {missing}. Provide all four --asc-api-* flags, or none."
            )

        if len(given) == len(asc_api_fields):
            adapter = AscApiAdapter(
                app_id=asc_api_app_id,
                key_id=asc_api_key_id,
                issuer_id=asc_api_issuer_id,
                key_path=asc_api_key,
            )
        elif yaml_path is not None:
            adapter = YamlAdapter(yaml_path)
        elif path is not None:
            adapter = FastlaneAdapter(path)
        else:
            raise typer.BadParameter("Provide a fastlane PATH or --yaml PATH.")

        with span("ingest"):
            meta = adapter.load()

        with span("deterministic"):
            det = run_deterministic(meta)

        guidelines = Guidelines(available=False, text="", sections={}, source="")
        verdicts = []
        panels: list[PanelVerdict] = []
        llm_skipped = True

        if not dry_run:
            with span("guidelines"):
                guidelines = get_guidelines(
                    session_id=uuid.uuid4().hex, override_path=guidelines_path
                )

            if jury_requested:
                judge_set = _build_judge_set(judges_path, judge_cli, consensus)
                panel = build_panel(judge_set.specs, judge_set.consensus, max_concurrency)
                if panel is None:
                    # Every configured judge is unavailable (no key/model) --
                    # degrade to deterministic-only, same as the v1 no-key path.
                    llm_skipped = True
                else:
                    with span("panel"):
                        panels = panel.run_panel(
                            meta,
                            guidelines,
                            DIMENSIONS,
                            screenshots=meta.screenshots,
                            vision_dimensions=VISION_DIMENSIONS,
                            no_vision=no_vision,
                        )
                    verdicts = [p.consensus for p in panels]
                    llm_skipped = False
            else:
                has_key_or_model = judge_model is not None or os.environ.get("ANTHROPIC_API_KEY")

                if has_key_or_model:
                    with span("judge"):
                        verdicts = judge_field(meta, guidelines, DIMENSIONS, model=judge_model)
                    llm_skipped = False

                if not no_vision and has_key_or_model and meta.screenshots:
                    with span("vision"):
                        verdicts = verdicts + judge_screenshots(
                            meta.screenshots, guidelines, model=judge_model
                        )

        with span("gate"):
            report = evaluate(
                verdicts,
                det,
                fail_on=fail_on,
                guidelines_available=guidelines.available,
                panels=panels,
            )

        return report, llm_skipped


@app.command()
def verify(
    path: Path | None = typer.Argument(
        None,
        help="Fastlane `deliver` root directory (the parent of metadata/ and "
        "screenshots/). Ignored when --yaml is given.",
    ),
    yaml_path: Path | None = typer.Option(
        None, "--yaml", help="Use the YAML adapter on this file instead of fastlane."
    ),
    asc_api_app_id: str | None = typer.Option(
        None,
        "--asc-api-app-id",
        help="App Store Connect app id. Requires all other --asc-api-* flags too; "
        "when all four are given, fetches live from the App Store Connect API "
        "instead of fastlane/--yaml.",
    ),
    asc_api_key_id: str | None = typer.Option(
        None, "--asc-api-key-id", help="App Store Connect API key id (from the .p8 key)."
    ),
    asc_api_issuer_id: str | None = typer.Option(
        None, "--asc-api-issuer-id", help="App Store Connect API issuer id."
    ),
    asc_api_key: Path | None = typer.Option(
        None,
        "--asc-api-key",
        help="Path to the App Store Connect API private key (.p8 file).",
    ),
    no_vision: bool = typer.Option(
        False,
        "--no-vision",
        help="Skip the vision screenshot judge (Task 17). The vision judge runs "
        "only when this is unset, an API key/model is available, and there are "
        "screenshots to judge.",
    ),
    output_format: OutputFormat = typer.Option(
        OutputFormat.md, "--format", help="Report output format."
    ),
    fail_on: FailOn = typer.Option(
        FailOn.fail, "--fail-on", help="Gate threshold: block on 'fail' or already on 'warn'."
    ),
    guidelines_path: Path | None = typer.Option(
        None,
        "--guidelines",
        help="Local offline copy of the App Store Review Guidelines (skips the live fetch).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Skip the guidelines fetch and the judge; deterministic + gate only (offline).",
    ),
    judges_path: Path | None = typer.Option(
        None,
        "--judges",
        help="Path to a judges.yaml jury config (see judges.example.yaml). Given alone or "
        "with --judge, this activates the multi-LLM jury instead of the single-judge path.",
    ),
    judge_cli: list[str] = typer.Option(
        None,
        "--judge",
        help="Add/override one jury judge inline: '[name=]provider:model[@base_url]', e.g. "
        "'anthropic:claude-sonnet-5'. Repeatable. Merges with --judges by name.",
    ),
    consensus: str | None = typer.Option(
        None,
        "--consensus",
        help="Consensus policy for the jury (majority_severe, most_severe, unanimous, "
        "confidence_weighted). Requires --judges and/or --judge.",
    ),
    max_concurrency: int = typer.Option(
        8, "--max-concurrency", help="Max concurrent jury judge calls in flight at once."
    ),
) -> None:
    """Verify App Store Connect metadata against deterministic checks and an LLM judge."""
    try:
        report, llm_skipped = run_verify(
            path=path,
            yaml_path=yaml_path,
            asc_api_app_id=asc_api_app_id,
            asc_api_key_id=asc_api_key_id,
            asc_api_issuer_id=asc_api_issuer_id,
            asc_api_key=asc_api_key,
            no_vision=no_vision,
            fail_on=fail_on.value,
            guidelines_path=guidelines_path,
            dry_run=dry_run,
            judges_path=judges_path,
            judge_cli=judge_cli,
            consensus=consensus,
            max_concurrency=max_concurrency,
        )
    except IngestError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    except JudgeConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    except (FileNotFoundError, OSError, ValueError):
        # `get_guidelines(override_path=...)` raises FileNotFoundError/OSError
        # for a missing/unreadable --guidelines override file, and ValueError
        # for an invalid session id -- neither is an IngestError, so without
        # this handler a bad --guidelines path leaks a raw traceback instead
        # of the actionable "no tracebacks" message the rest of the CLI gives.
        typer.echo(f"Error: guidelines file not found: {guidelines_path}", err=True)
        raise typer.Exit(code=2) from None

    if output_format is OutputFormat.json:
        # Raw JSON only on stdout (no rich decoration) so it stays pipeable/parseable.
        typer.echo(render_json(report))
    else:
        typer.echo(render_markdown(report))

    if llm_skipped and not dry_run:
        typer.echo("LLM checks skipped (no ANTHROPIC_API_KEY)", err=True)

    error_votes, empty_tally_units = compute_degradation(report.panels)
    if error_votes or empty_tally_units:
        # Same conservative-pass gate semantics as always (no exit-code
        # change) -- this just makes a degraded jury run visible to a
        # human/CI even in --format json mode, where the markdown note
        # (report.py's `_degradation_note`) wouldn't otherwise be seen.
        parts = []
        if error_votes:
            parts.append(f"{error_votes} judge call(s) failed")
        if empty_tally_units:
            parts.append(f"{empty_tally_units} unit(s) defaulted to pass")
        typer.echo(
            f"WARNING: jury degraded -- {', '.join(parts)} "
            "(see --format json for per-judge errors)",
            err=True,
        )

    raise typer.Exit(code=exit_code(report))
