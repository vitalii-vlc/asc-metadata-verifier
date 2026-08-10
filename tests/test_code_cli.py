"""CLI tests for the `code` command + `verify --code` (Task 8).

Uses real tree-sitter; skipped cleanly when the [code] extra is absent."""

import plistlib
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from typer.testing import CliRunner  # noqa: E402

from asc_metadata_verifier.cli import app  # noqa: E402

runner = CliRunner()


def _project(tmp_path: Path, swift: str, info: dict) -> Path:
    (tmp_path / "App").mkdir(parents=True, exist_ok=True)
    (tmp_path / "App/View.swift").write_text(swift)
    (tmp_path / "App/Info.plist").write_bytes(plistlib.dumps(info))
    return tmp_path


def test_code_command_blocks_on_uiwebview(tmp_path):
    _project(tmp_path, "let w = UIWebView()\n", {"ITSAppUsesNonExemptEncryption": False})
    res = runner.invoke(app, ["code", str(tmp_path)])
    assert res.exit_code == 1 and "uiwebview-usage" in res.output and "BLOCK" in res.output


def test_code_command_json_format(tmp_path):
    _project(tmp_path, "let w = UIWebView()\n", {"ITSAppUsesNonExemptEncryption": False})
    res = runner.invoke(app, ["code", str(tmp_path), "--format", "json"])
    assert res.exit_code == 1 and '"rule_id"' in res.output and '"parser_backend"' in res.output


def test_code_command_clean_project_passes(tmp_path):
    _project(
        tmp_path, "import WebKit\nlet w = WKWebView()\n", {"ITSAppUsesNonExemptEncryption": False}
    )
    res = runner.invoke(app, ["code", str(tmp_path)])
    assert res.exit_code == 0 and "PASS" in res.output


def test_code_command_missing_path_exits_2():
    res = runner.invoke(app, ["code", "/no/such/project/at/all"])
    assert res.exit_code == 2 and "not found" in res.output


def test_code_swiftsyntax_backend_falls_back_and_runs(tmp_path):
    # No helper configured -> swiftsyntax is unavailable -> falls back to
    # tree-sitter and still analyzes (must not traceback or exit 2).
    _project(tmp_path, "let w = UIWebView()\n", {"ITSAppUsesNonExemptEncryption": False})
    res = runner.invoke(app, ["code", str(tmp_path), "--backend", "swiftsyntax"])
    assert res.exit_code == 1 and "uiwebview-usage" in res.output


def test_verify_with_code_folds_findings(tmp_path):
    _project(tmp_path, "let w = UIWebView()\n", {"ITSAppUsesNonExemptEncryption": False})
    res = runner.invoke(
        app,
        ["verify", "--yaml", "tests/fixtures/metadata.yaml", "--dry-run", "--code", str(tmp_path)],
    )
    assert "uiwebview-usage" in res.output
