"""CLI tests for the `pages` command + `verify --pages` (Task 9). Offline via
--pages-dir (a pages.json manifest)."""

import json
from pathlib import Path

from typer.testing import CliRunner

from asc_metadata_verifier.cli import app

runner = CliRunner()


def _pages_dir(tmp_path: Path, pages: dict) -> Path:
    d = tmp_path / "pages"
    d.mkdir()
    manifest = {}
    for i, (url, html) in enumerate(pages.items()):
        fn = f"p{i}.html"
        (d / fn).write_text(html)
        manifest[url] = fn
    (d / "pages.json").write_text(json.dumps(manifest))
    return d


def test_pages_command_blocks_on_unreachable_privacy(tmp_path):
    # metadata.yaml declares privacy/support URLs; the pages-dir supplies neither
    d = _pages_dir(tmp_path, {"https://only/support": "<p>contact us at help@x.com anytime</p>"})
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/metadata.yaml",
                              "--pages-dir", str(d)])
    assert res.exit_code == 1 and "page-unreachable" in res.output


def test_pages_command_json_format(tmp_path):
    d = _pages_dir(tmp_path, {})
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/metadata.yaml",
                              "--pages-dir", str(d), "--format", "json"])
    assert '"rule_id"' in res.output and '"pages_checked"' in res.output


def test_pages_missing_metadata_source_exits_2():
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/does_not_exist.yaml"])
    assert res.exit_code == 2


def test_verify_with_pages_folds_findings(tmp_path):
    d = _pages_dir(tmp_path, {})
    res = runner.invoke(app, ["verify", "--yaml", "tests/fixtures/metadata.yaml", "--dry-run",
                              "--pages", "--pages-dir", str(d)])
    assert "page-unreachable" in res.output


def test_verify_with_code_and_pages_composes(tmp_path):
    import plistlib

    import pytest
    pytest.importorskip("tree_sitter_language_pack")
    (tmp_path / "App").mkdir()
    (tmp_path / "App/View.swift").write_text("let w = UIWebView()\n")
    (tmp_path / "App/Info.plist").write_bytes(
        plistlib.dumps({"ITSAppUsesNonExemptEncryption": False}))
    d = _pages_dir(tmp_path, {})
    res = runner.invoke(app, ["verify", "--yaml", "tests/fixtures/metadata.yaml", "--dry-run",
                              "--code", str(tmp_path), "--pages", "--pages-dir", str(d)])
    assert "uiwebview-usage" in res.output and "page-unreachable" in res.output
