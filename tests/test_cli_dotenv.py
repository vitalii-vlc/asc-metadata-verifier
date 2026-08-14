"""Tests for `.env` loading at the `asc-verify` entry point.

The tool reads its configuration (`ANTHROPIC_API_KEY`, `ASC_JUDGE_MODEL`,
`LOGFIRE_TOKEN`, ...) straight from `os.environ`. For a `.env` file to
actually work, the CLI entry point must load it *before* any command reads
the environment -- and it must not override a value already set in the real
environment (real env wins over `.env`).

Loading lives in a `main()` wrapper (the console-script target), not at
import time, so importing `cli` in-process (as the CliRunner tests do) never
picks up the repo's own `.env`.

A harmless, non-secret variable (`ASC_JUDGE_MODEL`) is used throughout --
never a real key -- and `monkeypatch` restores the environment after each
test.
"""

from __future__ import annotations

import os

from asc_metadata_verifier import cli


def test_load_env_reads_dotenv_from_cwd(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ASC_JUDGE_MODEL=from-dotenv-xyz\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASC_JUDGE_MODEL", raising=False)

    cli._load_env()

    assert os.environ["ASC_JUDGE_MODEL"] == "from-dotenv-xyz"


def test_real_env_wins_over_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ASC_JUDGE_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASC_JUDGE_MODEL", "from-real-env")

    cli._load_env()

    assert os.environ["ASC_JUDGE_MODEL"] == "from-real-env"


def test_load_env_is_a_noop_without_a_dotenv_file(tmp_path, monkeypatch):
    # No .env in an empty cwd -> nothing loaded, no error.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASC_JUDGE_MODEL", raising=False)

    cli._load_env()

    assert "ASC_JUDGE_MODEL" not in os.environ


def test_main_loads_env_before_running_app(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cli, "_load_env", lambda: calls.append("env"))
    monkeypatch.setattr(cli, "app", lambda: calls.append("app"))

    cli.main()

    assert calls == ["env", "app"]
