# ASC Metadata Verifier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `asc-metadata-verifier` — an LLM-as-judge CLI + bundled Claude skill that gates App Store Connect metadata for rejection risk, grounded in the live App Store Review Guidelines, traced in Logfire.

**Architecture:** Ingest adapters (fastlane/YAML/ASC-API) normalize into a canonical `AppMetadata`; deterministic checks settle what a regex can; a pydantic-ai judge (Claude), grounded in live-fetched guidelines, scores each rubric dimension into structured `RubricVerdict`s; a gate aggregates to PASS/WARN/BLOCK; a golden dataset + pydantic-evals measure the judge itself. Packaged as a pip library that bundles the `app-store-review-gate` skill via the `library-skills` convention.

**Tech Stack:** Python ≥3.11 (uv) · pydantic-ai · pydantic-evals · logfire · pydantic v2 · httpx · PyJWT + cryptography · pyyaml · typer + rich · pytest.

## Global Constraints
- **Honesty bar (hard):** never fabricate a finding or a `guideline_ref`. Every `guideline_ref` cites the **live** App Store Review Guidelines fetched at review time; if the fetch fails, run without citations and flag "guideline references unavailable (offline)" — never invent one. Never invent the `library-skills` convention (Task 1 derives it from source).
- **Determinism first:** never call the LLM for what `checks/deterministic.py` settles (char counts, empties, obvious placeholders).
- **Offline-safe:** deterministic checks + the full CLI shape work with no `ANTHROPIC_API_KEY`; LLM/vision degrade gracefully with a clear flag.
- **Secrets:** `.p8` keys and API creds are never read from the repo and never logged; `.gitignore` already blocks `*.p8`, `.env`, guideline caches.
- **Guidelines cache is session-scoped:** fetched once per session into system temp, reused within the session, re-fetched next session, never committed.
- **Judge model:** default `claude-sonnet-5`, overridable via env `ASC_JUDGE_MODEL`.
- **Tests that hit the model** use pydantic-ai's `TestModel`/`FunctionModel` (no network); real-model tests are gated behind `ANTHROPIC_API_KEY` and skipped when absent so CI stays green offline.
- **Package layout:** `src/asc_metadata_verifier/…`; CLI entry point `asc-verify`.

## Field limits (exact — used by `limits.py`)
`app_name` 30 · `subtitle` 30 · `promotional_text` 170 · `keywords` 100 · `description` 4000 · `whats_new` (release notes) 4000. URL fields (`support_url`, `marketing_url`, `privacy_url`) validated as URLs, not length. Required per locale: `app_name`, `description`, `keywords`. Missing others → WARN, not BLOCK.

## Rubric dimensions (exact — the 8 MVP evaluators)
`placeholder_text` · `other_platform_mentions` (Android, Google Play, "also on…") · `misleading_claims` · `price_terms_in_description` · `keyword_stuffing` (incl. competitor names / irrelevant terms in `keywords`) · `beta_demo_mentions` · `unauthorized_contact_links` · `third_party_trademark`.

## `RubricVerdict` schema (exact)
```python
dimension: str                                   # one of the 8 rubric dimension ids
verdict: Literal["pass", "warn", "fail"]
severity: Literal["low", "medium", "high"]
confidence: float                                # 0.0–1.0
rationale: str
offending_quote: str | None = None               # verbatim span from the metadata
guideline_ref: str | None = None                 # e.g. "2.3.7" — only from live guidelines; None if offline
suggested_fix: str | None = None
locale: str                                      # e.g. "en-US"
field: str                                       # e.g. "description"
```

## Gate logic (exact — `gate.py`)
`BLOCK` if any verdict is `fail` with `severity == "high"`. `WARN` if any `fail`/`warn` exists but no high-severity fail. `PASS` otherwise. `--fail-on {warn,fail}` lowers the block threshold; default `--fail-on fail` (only high-severity fails block).

## File Structure
```
src/asc_metadata_verifier/
  __init__.py            models.py            limits.py            observability.py
  gate.py                report.py            cli.py
  ingest/    base.py  fastlane.py  yaml_source.py  asc_api.py(Phase2)
  checks/    deterministic.py
  guidelines/ source.py
  judge/     agent.py  rubric.py  vision.py(Phase2)
  evals/     dataset.py  meta_eval.py  golden/*.jsonl
  skill/     SKILL.md   (bundled skill; exact location per Task 1)
tests/  test_*.py  fixtures/{fastlane_flawed/, fastlane_clean/, metadata.yaml, screenshots/}
docs/  library-skills-convention.md (Task 1)
pyproject.toml  README.md  BUILD_LOG.md
```

---

### Task 1: Derive the `library-skills` bundling convention (research, NO guessing)
**Files:** Create `docs/library-skills-convention.md`
**Interfaces:** Produces the authoritative packaging recipe consumed by Task 14.

- [ ] **Step 1:** Read the source of truth — `github.com/tiangolo/library-skills` (repo + its own package code that does discovery) and a reference implementation that bundles a skill (e.g. FastAPI, Typer, or Streamlit). Determine, with citations: (a) the exact in-package path/folder where the skill file(s) live; (b) any `pyproject.toml` entry-point / package-data / config that makes discovery work; (c) the exact `SKILL.md` frontmatter fields `library-skills` reads; (d) the user install command (`uvx library-skills`).
- [ ] **Step 2:** Write `docs/library-skills-convention.md` recording the above **verbatim with source links**. If any element cannot be confirmed from source, mark it `UNCONFIRMED` and record the fallback (manual `~/.claude/skills/` install) — do not fabricate.
- [ ] **Step 3:** Commit: `git commit -m "docs: derive library-skills bundling convention from source"`

### Task 2: Project scaffold (uv package + tooling + smoke test)
**Files:** Create `pyproject.toml`, `src/asc_metadata_verifier/__init__.py`, `tests/test_smoke.py`
**Interfaces:** Produces installable package `asc_metadata_verifier` exposing console script `asc-verify` (wired in Task 12; a placeholder `main()` for now).

- [ ] **Step 1:** Write `tests/test_smoke.py`: `import asc_metadata_verifier; assert asc_metadata_verifier.__version__`
- [ ] **Step 2:** Run `uv run pytest tests/test_smoke.py` → FAIL (module/attr missing).
- [ ] **Step 3:** Write `pyproject.toml` (build-system, deps from Tech Stack pinned to available versions, `[project.scripts] asc-verify = "asc_metadata_verifier.cli:app"`, ruff + pytest config), and `__init__.py` with `__version__ = "0.1.0"`. `uv sync`.
- [ ] **Step 4:** Run `uv run pytest` → PASS. `uv run ruff check .` clean.
- [ ] **Step 5:** Commit: `feat: project scaffold (uv package, tooling, smoke test)`

### Task 3: Canonical models
**Files:** Create `src/asc_metadata_verifier/models.py`, `tests/test_models.py`
**Interfaces:** Produces `LocaleMetadata`, `Screenshot`, `AppMetadata`, `RubricVerdict` (schema above), `GateReport{status: Literal["PASS","WARN","BLOCK"], verdicts: list[RubricVerdict], deterministic_findings: list[...], guidelines_available: bool}`.

- [ ] **Step 1:** Write `tests/test_models.py`: construct an `AppMetadata` with two locales; assert round-trip `model_dump`/`model_validate`; assert `RubricVerdict` rejects an out-of-range `confidence` (>1.0) and an invalid `verdict` literal.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the pydantic v2 models per the schemas above.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat: canonical metadata + verdict models`

### Task 4: Field limits + required fields
**Files:** Create `src/asc_metadata_verifier/limits.py`, `tests/test_limits.py`
**Interfaces:** Produces `FIELD_LIMITS: dict[str,int]`, `REQUIRED_FIELDS: set[str]`, `over_limit(field, value) -> int | None` (returns overflow count or None).

- [ ] **Step 1:** Test: `over_limit("app_name", "x"*31) == 1`; `over_limit("app_name","ok") is None`; `"keywords" in REQUIRED_FIELDS`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement with the exact limits above. **Step 4:** PASS. **Step 5:** Commit: `feat: App Store field limits + required fields`

### Task 5: Deterministic checks
**Files:** Create `src/asc_metadata_verifier/checks/deterministic.py`, `tests/test_deterministic.py`
**Interfaces:** Consumes `AppMetadata`. Produces `run_deterministic(meta) -> list[DeterministicFinding{locale,field,kind,detail}]`. Kinds: `over_limit`, `missing_required`, `placeholder`, `malformed_url`. Placeholder regex set: `\blorem\b`, `\bipsum\b`, `TODO`, `XXX`, `FIXME`, `placeholder`, `\bTBD\b` (case-insensitive).

- [ ] **Step 1:** Test on a fixture with `description="Lorem ipsum TODO"`, `app_name` 31 chars, empty `keywords`, `support_url="notaurl"` → expect findings of kinds `placeholder`, `over_limit`, `missing_required`, `malformed_url`. Assert a clean fixture yields `[]`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (LLM-free). **Step 4:** PASS. **Step 5:** Commit: `feat: deterministic pre-checks (limits, placeholders, urls)`

### Task 6: Ingestion base + fastlane adapter
**Files:** Create `src/asc_metadata_verifier/ingest/base.py`, `ingest/fastlane.py`, `tests/test_ingest_fastlane.py`, `tests/fixtures/fastlane_clean/…`
**Interfaces:** `base.IngestAdapter` protocol: `load() -> AppMetadata`. `fastlane.FastlaneAdapter(path)` reads `metadata/<locale>/{name,subtitle,description,keywords,promotional_text,release_notes,support_url,marketing_url,privacy_url}.txt` and `screenshots/<locale>/*` → `AppMetadata`.

- [ ] **Step 1:** Create a minimal `fastlane_clean` fixture (2 locales, a couple screenshots). Test: `FastlaneAdapter(fixture).load()` yields both locales with expected `app_name`/`description`, screenshot paths populated. Test a missing-locale dir → clear error, not a traceback.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit: `feat: fastlane deliver ingestion adapter`

### Task 7: YAML adapter
**Files:** Create `src/asc_metadata_verifier/ingest/yaml_source.py`, `tests/test_ingest_yaml.py`, `tests/fixtures/metadata.yaml`
**Interfaces:** `YamlAdapter(path).load() -> AppMetadata`. YAML shape: `locales: {en-US: {app_name, subtitle, description, keywords, …}}`, optional `screenshots: {en-US: [paths]}`.

- [ ] **Step 1:** Fixture + test: parsed `AppMetadata` matches the YAML; malformed YAML → actionable error. **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit: `feat: YAML/JSON ingestion adapter`

### Task 8: Guidelines source (live fetch · session cache · offline)
**Files:** Create `src/asc_metadata_verifier/guidelines/source.py`, `tests/test_guidelines.py`
**Interfaces:** `GUIDELINES_URL = "https://developer.apple.com/app-store/review/guidelines/"`. `get_guidelines(session_id, override_path=None, client=None) -> Guidelines{available: bool, text: str, sections: dict[str,str], source: str}`. Session cache in `tempfile.gettempdir()/asc_cache/<session_id>.guidelines.json`; reuse if present; fetch via injected `httpx.Client` otherwise; extract metadata-relevant sections (esp. 2.3). On fetch failure → `available=False`, empty text, no exception. `override_path` loads a local copy (offline).

- [ ] **Step 1:** Test with a **mocked** httpx client returning fixture HTML: first call fetches + writes cache; second call (same session) reads cache without re-fetching (assert client called once). Test fetch-raises → `available is False`, no exception. Test `override_path` bypasses network.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (inject the client so tests never hit the network). **Step 4:** PASS. **Step 5:** Commit: `feat: live App Store Review Guidelines source (session-cached, offline-safe)`

### Task 9: Judge agent + rubric
**Files:** Create `src/asc_metadata_verifier/judge/rubric.py`, `judge/agent.py`, `tests/test_judge.py`
**Interfaces:** `rubric.DIMENSIONS: list[RubricDimension{id, description, guideline_hint}]` (the 8 above). `agent.build_judge(model=None) -> pydantic_ai.Agent[..., RubricVerdict]` with `output_type=RubricVerdict`, a system prompt that (a) states the dimension, (b) injects the live guidelines section as grounding, (c) forbids inventing `guideline_ref` (must be `None` if guidelines unavailable). `agent.judge_field(meta, guidelines, dimensions, model=None) -> list[RubricVerdict]`.

- [ ] **Step 1:** Test with pydantic-ai `TestModel`/`FunctionModel` (no network): feed a field containing "Also available on Android" → the `other_platform_mentions` path produces a `fail`/`warn` verdict with an `offending_quote`; feed clean text → `pass`. Assert that when `guidelines.available is False`, produced verdicts have `guideline_ref is None`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement rubric prompts + agent; grounding text passed in, never fabricated. **Step 4:** PASS. **Step 5:** Commit: `feat: pydantic-ai rejection-risk judge grounded in live guidelines`

### Task 10: Observability (Logfire)
**Files:** Create `src/asc_metadata_verifier/observability.py`, `tests/test_observability.py`
**Interfaces:** `configure_logfire()` calls `logfire.configure(send_to_logfire="if-token-present", service_name="asc-metadata-verifier")` + `logfire.instrument_pydantic_ai()`; `span(name, **attrs)` helper.

- [ ] **Step 1:** Test: `configure_logfire()` runs without raising and without a token (no network); `span("x")` context manager works.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit: `feat: Logfire observability wiring`

### Task 11: Gate + report
**Files:** Create `src/asc_metadata_verifier/gate.py`, `report.py`, `tests/test_gate.py`, `tests/test_report.py`
**Interfaces:** `gate.evaluate(verdicts, deterministic_findings, fail_on="fail") -> GateReport`. `report.render_markdown(report)`, `report.render_json(report)`, `report.exit_code(report) -> int` (0 PASS/WARN, non-zero BLOCK).

- [ ] **Step 1:** Tests: a high-severity `fail` → `BLOCK` + exit non-zero; only `warn`s → `WARN` + exit 0; `--fail-on warn` turns a `warn` into `BLOCK`; JSON round-trips; markdown groups by locale × dimension and includes quotes/refs/fixes.
- [ ] **Step 2:** FAIL. **Step 3:** Implement per the exact gate logic. **Step 4:** PASS. **Step 5:** Commit: `feat: gate aggregation + markdown/json report + exit codes`

### Task 12: CLI (typer)
**Files:** Create `src/asc_metadata_verifier/cli.py`, `tests/test_cli.py`
**Interfaces:** `app = typer.Typer()`; command `verify(path=None, --yaml, --asc-api…, --no-vision, --rubric, --format, --fail-on, --guidelines, --dry-run)`. Orchestrates: pick adapter → `load()` → deterministic → `get_guidelines()` → judge (unless no key: skip + flag) → gate → render → exit code. Logfire spans around each phase.

- [ ] **Step 1:** Test via `typer.testing.CliRunner` on the `fastlane_clean` fixture with `--no-vision` and no API key: exits 0, prints a PASS/WARN report, notes "LLM checks skipped" when no key. Test `--format json` emits valid JSON. (Judge path here uses a fake model via a `--model test` hook or dependency injection.)
- [ ] **Step 2:** FAIL. **Step 3:** Implement wiring. **Step 4:** PASS. **Step 5:** Commit: `feat: asc-verify CLI orchestration`

### Task 13: Golden dataset + pydantic-evals meta-eval
**Files:** Create `src/asc_metadata_verifier/evals/golden/*.jsonl`, `evals/dataset.py`, `evals/meta_eval.py`, `tests/test_meta_eval.py`
**Interfaces:** `golden/*.jsonl` = 30–50 labeled cases `{text, locale, field, expected_dimension, expected_verdict, source_note}` drawn from real rejection reasons + clean controls. `dataset.build_dataset()` → pydantic-evals `Dataset`. `meta_eval.run(model=None) -> MetaEvalReport{per_dimension_precision, recall, accuracy, failure_taxonomy}`. Pre-register the expected accuracy in `BUILD_LOG.md` **before** first real run.

- [ ] **Step 1:** Curate the golden set (label carefully — garbage labels invalidate the stats). Test with a `FunctionModel` stub: `dataset` loads all cases; `meta_eval.run(model=stub)` returns a report with per-dimension precision/recall keys and a numeric accuracy; assert the failure_taxonomy captures a deliberate stub-miss.
- [ ] **Step 2:** FAIL. **Step 3:** Implement dataset + evaluators (label-vs-verdict agreement). **Step 4:** PASS. Add a **real-model** meta-eval test gated behind `ANTHROPIC_API_KEY` (skipped in CI). **Step 5:** Commit: `feat: golden dataset + pydantic-evals judge meta-eval (agreement stats)`

### Task 14: Bundle the Claude skill (`library-skills` convention) + manual fallback
**Files:** Create `src/asc_metadata_verifier/skill/SKILL.md` (or the exact path Task 1 derived), update `pyproject.toml` (package-data / entry-point per Task 1), `tests/test_skill_packaging.py`
**Interfaces:** `SKILL.md` (frontmatter per Task 1): skill `app-store-review-gate` — instructs Claude to run `asc-verify` on a given app, interpret the JSON, present the gate + prioritized fixes, and refuse to proceed to `ios-fastlane-ship` on BLOCK. Fallback: README documents copying `SKILL.md` into `~/.claude/skills/app-store-review-gate/`.

- [ ] **Step 1:** Test: the skill file is included in the built wheel at the path `library-skills` expects (build the wheel, assert the skill path is present); `SKILL.md` frontmatter has the required fields from Task 1. If Task 1 marked the convention `UNCONFIRMED`, this task ships the manual-fallback install only and the test asserts the fallback path works.
- [ ] **Step 2:** FAIL. **Step 3:** Implement per the derived convention. **Step 4:** PASS. Manually verify `uvx library-skills` discovers it (or the fallback). **Step 5:** Commit: `feat: bundle app-store-review-gate skill via library-skills convention`

### Task 15: End-to-end + docs
**Files:** Create `tests/fixtures/fastlane_flawed/…`, `tests/test_e2e.py`, finalize `README.md`, `BUILD_LOG.md`
**Interfaces:** A deliberately-flawed fastlane fixture (Android mention, placeholder text, over-limit name, price in description) → full run → `BLOCK` with the specific findings.

- [ ] **Step 1:** Build the flawed fixture. Test: `CliRunner` full run (fake model returning the expected fails) → exit non-zero, report names each planted issue with dimension + fix. **Step 2:** FAIL. **Step 3:** Wire any gaps. **Step 4:** PASS. Write honest `BUILD_LOG.md` (pre-registered estimate 7d, actuals, where the AI/judge missed). **Step 5:** Commit: `test: e2e flawed-app BLOCK + docs/build-log`

--- END PHASE 1 ---

### Task 16 (Phase 2): App Store Connect API adapter
**Files:** Create `src/asc_metadata_verifier/ingest/asc_api.py`, `tests/test_ingest_asc_api.py`
**Interfaces:** `AscApiAdapter(app_id, key_id, issuer_id, key_path).load() -> AppMetadata`. JWT (ES256) auth via PyJWT+cryptography; fetch app info + version localizations + screenshots via httpx from `api.appstoreconnect.apple.com`.

- [ ] **Step 1:** Test with **mocked** httpx returning recorded ASC API JSON: mapping → `AppMetadata` across locales; a bad `.p8`/expired token → actionable error. Never read a real key in tests. **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit: `feat: App Store Connect API ingestion adapter (Phase 2)`

### Task 17 (Phase 2): Vision judge for screenshots
**Files:** Create `src/asc_metadata_verifier/judge/vision.py`, `tests/test_vision.py`, `tests/fixtures/screenshots/{bad,good}.png`
**Interfaces:** `judge_screenshots(screenshots, guidelines, model=None) -> list[RubricVerdict]` (dimensions: `placeholder_image`, `other_platform_ui`, `misleading_screenshot`, `excessive_text`). Wire into CLI unless `--no-vision`.

- [ ] **Step 1:** Test with a fake vision-capable model: a "bad" screenshot fixture → a `fail` verdict; a "good" one → `pass`; unreadable image → skipped with a warning, run continues. **Step 2:** FAIL. **Step 3:** Implement (pydantic-ai image input). **Step 4:** PASS. **Step 5:** Commit: `feat: vision screenshot judge (Phase 2)`

---

## Self-review
- **Spec coverage:** all three ingest sources (T6/T7/T16), deterministic checks (T5), live-guidelines grounding (T8), rejection-risk judge (T9), Logfire (T10), gate/report/exit (T11), CLI (T12), golden meta-eval (T13), library-skills packaging + fallback (T1/T14), vision (T17), e2e + honest build-log (T15). ✓
- **Placeholder scan:** exact values are pinned in the plan header (field limits, 8 rubric dims, `RubricVerdict` schema, gate logic, model id, guidelines URL) so no task ships a vague "add validation". The one deliberate unknown (`library-skills` convention) is a research task (T1) with an explicit fabrication-forbidden rule and a fallback. ✓
- **Type consistency:** `AppMetadata`/`RubricVerdict`/`GateReport` defined once in T3 and consumed unchanged downstream; `verdict`/`severity` literals are identical in the schema and gate logic. ✓
- **TDD + independently testable:** every task is test-first and ends with a green, committable deliverable; model-hitting tests use `TestModel`/`FunctionModel` so the suite runs offline. ✓
