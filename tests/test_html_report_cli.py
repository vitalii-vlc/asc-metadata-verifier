"""CLI tests for --format html on verify/code/pages (Task 5)."""

import json
import plistlib

import pytest
from typer.testing import CliRunner

from asc_metadata_verifier.cli import app

runner = CliRunner()


def test_verify_format_html_emits_report():
    res = runner.invoke(app, ["verify", "--yaml", "tests/fixtures/metadata.yaml",
                              "--dry-run", "--format", "html"])
    assert res.exit_code == 0 and "<style>" in res.output
    assert "App Store Review Gate" in res.output  # masthead present
    assert "Pages analysis" not in res.output  # not the pages text report


def test_pages_format_html_emits_report(tmp_path):
    d = tmp_path / "pages"
    d.mkdir()
    (d / "pages.json").write_text(json.dumps({}))
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/metadata.yaml",
                              "--pages-dir", str(d), "--format", "html"])
    assert "<style>" in res.output and "page-unreachable" in res.output


def test_code_format_html_emits_report(tmp_path):
    pytest.importorskip("tree_sitter_language_pack")
    (tmp_path / "App").mkdir()
    (tmp_path / "App/View.swift").write_text("let w = UIWebView()\n")
    (tmp_path / "App/Info.plist").write_bytes(
        plistlib.dumps({"ITSAppUsesNonExemptEncryption": False}))
    res = runner.invoke(app, ["code", str(tmp_path), "--format", "html"])
    assert "<style>" in res.output and "uiwebview-usage" in res.output
