"""Judge configuration: `JudgeSpec`s from `judges.yaml` and/or `--judge` CLI
mini-syntax, with API-key/base-url availability resolved once at load time.

Secrets are handled by reference only: a spec carries `api_key_env` (a name)
and, once resolved, `api_key` (the value read from that env var) -- never a
literal key from YAML, and no error message below ever includes a key value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError

from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES

_DEFAULT_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class JudgeConfigError(Exception):
    """Raised for any malformed/invalid judge configuration. Messages are
    always actionable and free of secrets (they name env vars, never values).
    """


class JudgeSpec(BaseModel):
    name: str
    provider: Literal["anthropic", "openai"]
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    vision: bool = False
    # Resolved at load time, not read from YAML/CLI input directly.
    available: bool = True
    api_key: str | None = None


@dataclass
class JudgeSet:
    specs: list[JudgeSpec]
    consensus: str


def _resolve_availability(spec: JudgeSpec) -> JudgeSpec:
    """Fill in a default `api_key_env` per provider when absent, read the key
    from the environment, and derive `available`. Returns a new spec (specs
    are immutable inputs to this function).
    """
    api_key_env = spec.api_key_env or _DEFAULT_API_KEY_ENV[spec.provider]
    key = os.environ.get(api_key_env)
    available = key is not None or spec.base_url is not None
    return spec.model_copy(update={
        "api_key_env": api_key_env,
        "api_key": key,
        "available": available,
    })


def _build_spec(raw: dict[str, Any]) -> JudgeSpec:
    # Only the six known-safe fields are ever read from `raw` -- anything
    # else the user put in the mapping (by mistake or otherwise) is neither
    # forwarded to JudgeSpec nor echoed in the error below, so a stray
    # secret-shaped key in a malformed entry can never leak into a message.
    name = raw.get("name")
    provider = raw.get("provider")
    model = raw.get("model")
    try:
        return JudgeSpec(
            name=name,
            provider=provider,
            model=model,
            api_key_env=raw.get("api_key_env"),
            base_url=raw.get("base_url"),
            vision=raw.get("vision", False),
        )
    except ValidationError as exc:
        raise JudgeConfigError(
            f"Invalid judge entry (name={name!r}, provider={provider!r}, model={model!r}): {exc}"
        ) from exc


def load_judges(path) -> JudgeSet:
    """Parse, validate, and resolve availability for a `judges.yaml` file."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise JudgeConfigError(f"Malformed YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise JudgeConfigError(
            f"{path}: top-level YAML must be a mapping with a 'judges' key, "
            f"got {type(raw).__name__}"
        )

    judges_raw = raw.get("judges")
    if not judges_raw:
        raise JudgeConfigError(f"{path}: 'judges' is missing or empty")
    if not isinstance(judges_raw, list):
        raise JudgeConfigError(f"{path}: 'judges' must be a list")

    consensus = raw.get("consensus", DEFAULT_POLICY)
    if consensus not in POLICIES:
        raise JudgeConfigError(
            f"{path}: unknown consensus policy {consensus!r}; "
            f"must be one of {sorted(POLICIES)}"
        )

    specs: list[JudgeSpec] = []
    seen: set[str] = set()
    for entry in judges_raw:
        if not isinstance(entry, dict):
            raise JudgeConfigError(f"{path}: each judge entry must be a mapping, got {entry!r}")
        spec = _build_spec(entry)
        if spec.name in seen:
            raise JudgeConfigError(f"{path}: duplicate judge name {spec.name!r}")
        seen.add(spec.name)
        specs.append(_resolve_availability(spec))

    return JudgeSet(specs=specs, consensus=consensus)


def _parse_cli_spec(text: str, index: int) -> JudgeSpec:
    """Parse one `--judge` mini-syntax entry:
    `[name=]provider:model[@base_url]`.
    """
    name = None
    rest = text
    if "=" in text:
        name, rest = text.split("=", 1)

    if ":" not in rest:
        raise JudgeConfigError(
            f"Invalid --judge spec {text!r}: expected 'provider:model', e.g. 'anthropic:claude'"
        )
    provider, model_and_url = rest.split(":", 1)

    base_url = None
    model = model_and_url
    if "@" in model_and_url:
        model, base_url = model_and_url.split("@", 1)

    if not name:
        name = f"judge{index}"

    try:
        spec = JudgeSpec(name=name, provider=provider, model=model, base_url=base_url)
    except ValidationError as exc:
        raise JudgeConfigError(f"Invalid --judge spec {text!r}: {exc}") from exc

    return spec


def judges_from_cli(specs: list[str]) -> list[JudgeSpec]:
    """Parse `--judge` mini-syntax strings into resolved `JudgeSpec`s."""
    parsed = [_parse_cli_spec(text, i) for i, text in enumerate(specs)]
    return [_resolve_availability(spec) for spec in parsed]


def merge_specs(file_specs: list[JudgeSpec], cli_specs: list[JudgeSpec]) -> list[JudgeSpec]:
    """CLI specs override file specs by name; unmatched CLI specs are appended."""
    merged = {spec.name: spec for spec in file_specs}
    for spec in cli_specs:
        merged[spec.name] = spec
    return list(merged.values())
