"""Tracing tests: the `verify` pipeline must emit a connected span tree that
covers the code analyzer and the page fetches, not just the metadata pass.

Spans are captured with a plain OTel in-memory exporter rather than
`logfire.testing` -- the latter imports pytest, so it is unavailable in a
production (`--no-dev`) install, and these assertions should hold there too.
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

import logfire  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from typer.testing import CliRunner  # noqa: E402

from asc_metadata_verifier import cli  # noqa: E402

runner = CliRunner()

FIXTURE_ROOT = str(Path(__file__).parent / "fixtures" / "fastlane_clean")


@pytest.fixture
def spans(monkeypatch):
    """Capture every span the CLI emits during one invocation.

    Logfire is configured once here, with our exporter attached; the CLI's own
    `configure_logfire()` calls become no-ops, mirroring what its idempotence
    guarantee does in production. Configuring per call instead would swap the
    tracer provider mid-run and discard the enclosing span.
    """
    exporter = InMemorySpanExporter()
    logfire.configure(
        send_to_logfire=False,
        service_name="asc-metadata-verifier-test",
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    monkeypatch.setattr(cli, "configure_logfire", lambda: None)
    return exporter


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "App").mkdir(parents=True)
    (root / "App/View.swift").write_text('let s = "hello"\n')
    return root


def _pages_dir(tmp_path: Path) -> Path:
    d = tmp_path / "pages"
    d.mkdir()
    (d / "pages.json").write_text(json.dumps({}))
    return d


def test_verify_emits_spans_for_the_code_and_pages_stages(spans, tmp_path):
    runner.invoke(app_args := cli.app, [
        "verify", FIXTURE_ROOT, "--dry-run",
        "--code", str(_project(tmp_path)),
        "--pages", "--pages-dir", str(_pages_dir(tmp_path)),
    ])
    assert app_args is cli.app  # guard against a silently renamed CLI object

    names = {s.name for s in spans.get_finished_spans()}
    assert {"code", "pages"} <= names


def test_verify_span_tree_is_connected(spans, tmp_path):
    runner.invoke(cli.app, [
        "verify", FIXTURE_ROOT, "--dry-run",
        "--code", str(_project(tmp_path)),
        "--pages", "--pages-dir", str(_pages_dir(tmp_path)),
    ])

    finished = spans.get_finished_spans()
    roots = [s for s in finished if s.parent is None]
    assert [r.name for r in roots] == ["verify"], "the run must be one trace, not several"

    root_id = roots[0].context.span_id
    children = {s.name for s in finished if s.parent and s.parent.span_id == root_id}
    assert {"code", "pages"} <= children


def test_ingest_stays_nested_under_the_root_span(spans, tmp_path):
    runner.invoke(cli.app, ["verify", FIXTURE_ROOT, "--dry-run"])

    finished = spans.get_finished_spans()
    by_id = {s.context.span_id: s for s in finished}
    ingest = next(s for s in finished if s.name == "ingest")

    ancestors = []
    cur = ingest
    while cur.parent and cur.parent.span_id in by_id:
        cur = by_id[cur.parent.span_id]
        ancestors.append(cur.name)
    assert ancestors[-1] == "verify"
