"""`asc-verify`: the CLI that orchestrates the full verification pipeline.

Pipeline: pick an ingest adapter -> `load()` -> deterministic checks ->
guidelines fetch -> LLM judge (skipped when no key/model is available) ->
gate -> render -> exit code.

The pipeline logic lives in `run_verify`, a plain function with no typer/click
dependency, so it can be called and tested directly. The `verify` typer
command is a thin wrapper: arg parsing, printing, and exit-code translation.

Every collaborator is imported at module level (not inside functions) so
tests -- and Task 15's flawed-app e2e -- can monkeypatch them directly on
this module (e.g. `monkeypatch.setattr(cli, "judge_field", fake)`), which is
also how tests avoid a real network call to the live guidelines source.
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
from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.ingest.fastlane import FastlaneAdapter
from asc_metadata_verifier.ingest.yaml_source import YamlAdapter
from asc_metadata_verifier.judge.agent import judge_field
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.observability import configure_logfire, span
from asc_metadata_verifier.report import exit_code, render_json, render_markdown

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from asc_metadata_verifier.models import GateReport

app = typer.Typer(add_completion=False, no_args_is_help=False)


class OutputFormat(StrEnum):
    md = "md"
    json = "json"


class FailOn(StrEnum):
    warn = "warn"
    fail = "fail"


def run_verify(
    *,
    path: str | Path | None = None,
    yaml_path: str | Path | None = None,
    no_vision: bool = False,
    fail_on: str = "fail",
    guidelines_path: str | Path | None = None,
    dry_run: bool = False,
    judge_model: Model | str | None = None,
) -> tuple[GateReport, bool]:
    """Run the full verification pipeline; return `(report, llm_skipped)`.

    Adapter selection: `yaml_path` (if given) wins and uses `YamlAdapter`;
    otherwise `path` is used with `FastlaneAdapter`. If neither is given,
    raises `typer.BadParameter` (a usage error typer/click renders as an
    actionable message with exit code 2, without a traceback).

    `no_vision` is accepted for CLI-shape stability only: vision checks are
    Phase 2 (Task 17) and are never run in this phase regardless of its value.

    In `dry_run` mode, guidelines are never fetched and the judge never runs
    -- deterministic checks + gate only, so the command works fully offline
    with no network and no API key. Outside `dry_run`, the judge itself only
    runs when `judge_model` is injected or `ANTHROPIC_API_KEY` is set in the
    environment; otherwise it is skipped and `llm_skipped` is True, but the
    deterministic report + gate + exit code are still produced.
    """
    del no_vision  # Phase 2 (Task 17); accepted now only to keep the CLI shape stable.

    configure_logfire()
    with span("verify"):
        if yaml_path is not None:
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
        llm_skipped = True

        if not dry_run:
            with span("guidelines"):
                guidelines = get_guidelines(
                    session_id=uuid.uuid4().hex, override_path=guidelines_path
                )

            if judge_model is not None or os.environ.get("ANTHROPIC_API_KEY"):
                with span("judge"):
                    verdicts = judge_field(meta, guidelines, DIMENSIONS, model=judge_model)
                llm_skipped = False

        with span("gate"):
            report = evaluate(
                verdicts, det, fail_on=fail_on, guidelines_available=guidelines.available
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
    no_vision: bool = typer.Option(
        False,
        "--no-vision",
        help="Reserved for Phase 2 (Task 17): vision checks never run yet either way.",
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
) -> None:
    """Verify App Store Connect metadata against deterministic checks and an LLM judge."""
    try:
        report, llm_skipped = run_verify(
            path=path,
            yaml_path=yaml_path,
            no_vision=no_vision,
            fail_on=fail_on.value,
            guidelines_path=guidelines_path,
            dry_run=dry_run,
        )
    except IngestError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None

    if output_format is OutputFormat.json:
        # Raw JSON only on stdout (no rich decoration) so it stays pipeable/parseable.
        typer.echo(render_json(report))
    else:
        typer.echo(render_markdown(report))

    if llm_skipped and not dry_run:
        typer.echo("LLM checks skipped (no ANTHROPIC_API_KEY)", err=True)

    raise typer.Exit(code=exit_code(report))
