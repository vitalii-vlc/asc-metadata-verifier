import pytest

from asc_metadata_verifier.judge.config import (
    JudgeConfigError,
    judges_from_cli,
    load_judges,
    merge_specs,
)


def _write(tmp_path, text):
    p = tmp_path / "judges.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_specs_and_resolves_availability(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = _write(tmp_path, """
consensus: most_severe
judges:
  - {name: claude, provider: anthropic, model: claude-sonnet-5, vision: true}
  - {name: gpt4o, provider: openai, model: gpt-4o, api_key_env: OPENAI_API_KEY}
  - {name: local, provider: openai, model: llama3, base_url: http://localhost:11434/v1}
""")
    js = load_judges(p)
    assert js.consensus == "most_severe"
    by = {s.name: s for s in js.specs}
    assert by["claude"].available is True and by["claude"].vision is True
    assert by["gpt4o"].available is False            # OPENAI_API_KEY unset, no base_url
    assert by["local"].available is True             # base_url present, key not required


def test_default_consensus_is_majority_severe(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    p = _write(tmp_path, "judges:\n  - {name: c, provider: anthropic, model: m}\n")
    assert load_judges(p).consensus == "majority_severe"


def test_unknown_provider_raises(tmp_path):
    p = _write(tmp_path, "judges:\n  - {name: c, provider: gemini, model: m}\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_duplicate_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    p = _write(tmp_path, "judges:\n  - {name: c, provider: anthropic, model: m}\n"
                          "  - {name: c, provider: anthropic, model: n}\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_bad_consensus_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    p = _write(tmp_path, "consensus: bogus\njudges:\n"
                          "  - {name: c, provider: anthropic, model: m}\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_empty_judges_raises(tmp_path):
    p = _write(tmp_path, "judges: []\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_non_mapping_judge_entry_does_not_leak_its_value(tmp_path):
    secret = "sk-ant-secret-123"
    p = _write(tmp_path, f"judges:\n  - {secret}\n")
    with pytest.raises(JudgeConfigError) as exc_info:
        load_judges(p)
    assert secret not in str(exc_info.value)


def test_missing_judges_file_raises_judge_config_error(tmp_path):
    p = tmp_path / "does_not_exist.yaml"
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_cli_mini_syntax_parses_named_and_bare_and_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    specs = judges_from_cli([
        "big=anthropic:claude-opus-4-8",
        "openai:gpt-4o",
        "local=openai:llama3@http://localhost:11434/v1",
    ])
    by = {s.name: s for s in specs}
    assert by["big"].provider == "anthropic" and by["big"].model == "claude-opus-4-8"
    assert by["local"].base_url == "http://localhost:11434/v1" and by["local"].available is True
    assert any(s.provider == "openai" and s.model == "gpt-4o" for s in specs)  # bare -> auto name


def test_merge_cli_overrides_file_by_name():
    from asc_metadata_verifier.judge.config import JudgeSpec
    file_specs = [JudgeSpec(name="claude", provider="anthropic", model="sonnet"),
                  JudgeSpec(name="gpt", provider="openai", model="gpt-4o")]
    cli_specs = [JudgeSpec(name="claude", provider="anthropic", model="opus")]
    merged = {s.name: s for s in merge_specs(file_specs, cli_specs)}
    assert merged["claude"].model == "opus" and "gpt" in merged and len(merged) == 2
