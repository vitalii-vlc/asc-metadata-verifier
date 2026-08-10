# Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in persistence layer — run history, cross-run diff, a content-hash verdict cache, guideline snapshots, and optional semantic recall — behind a repository pattern with a stdlib-`sqlite3` default, without changing the tool's default offline behavior.

**Architecture:** A `persistence/` package: pydantic record models, a `Repository` protocol (structured store) with a `SqliteRepository` default + a backend registry, a pure `diff` module, a `cache` key module, and (Phase 2) a `semantic` module (Embedder/SemanticIndex protocols + Chroma). The CLI gains `history`/`diff`/`similar` subcommands while `asc-verify <path>` (no subcommand) keeps working via a default-command group.

**Tech Stack:** Python 3.11 (uv) · `sqlite3` (stdlib — no new core dep) · pydantic v2 · typer + click (default-command group) · hashlib. Optional `[semantic]` extra: `chromadb`; embedder is bring-your-own.

## Global Constraints

- **Opt-in / additive / backward compatible:** no `--db` and no persistence config → behavior byte-identical, no persistence I/O, zero new deps. Every existing test passes unchanged, including `asc-verify <fastlane-path>` invoked with **no subcommand**.
- **Cache correctness is an honesty invariant:** a verdict-cache hit must be the *identical* computation — same built prompt, judge model, and system-prompt version. Any difference is a miss. The cache never alters a verdict's content. `--no-cache` forces fresh. Cache defaults **OFF**.
- **Offline-safe:** persistence is fully testable with a temp SQLite file + a deterministic stub embedder — no network, no key. Default install pulls no `chromadb`, downloads nothing.
- **Secrets by reference:** a credentialed backend URL is never logged or echoed in errors.
- **A persistence failure never discards the gate result:** the report + exit code are produced first; a save failure is a stderr warning, never a swallowed error or a crash that hides the gate decision.
- **Style:** ruff (`E,F,I,UP,B`), line-length 100, py311. Every task ends green: `uv run pytest -q` all pass + `uv run ruff check .` clean, then commit.

---

## File Structure

**New package `src/asc_metadata_verifier/persistence/`**
- `__init__.py` (empty)
- `models.py` — `RunRecord`, `RunSummary`, `FindingStatus` (enum), `FindingDelta`, `RunDiff`.
- `cache.py` — `PROMPT_VERSION`, `verdict_cache_key`, `snapshot_hash`, `VerdictCache` adapter.
- `repository.py` — `Repository` Protocol, `RepositoryError`.
- `sqlite_repo.py` — `SqliteRepository`.
- `diff.py` — `diff_runs`, `render_diff_markdown`, `render_diff_json`.
- `config.py` — `resolve_repository`, `BACKENDS` registry.
- `semantic.py` *(Phase 2)* — `Embedder`, `StubEmbedder`, `SemanticIndex`, `InMemoryIndex`, `ChromaIndex`.

**Changed**
- `judge/agent.py` — `judge_field(..., cache=None)` optional seam.
- `cli.py` — default-command group + `history`/`diff`/`similar` subcommands + `verify --db/--cache/--no-cache/--no-save` + save wiring.
- `pyproject.toml` — `[project.optional-dependencies] semantic`.
- `.gitignore` — `.asc-verify/`.
- `README.md`, `BUILD_LOG.md`.

**Tests:** `tests/test_persistence_models.py`, `tests/test_cache.py`, `tests/test_sqlite_repo.py`, `tests/test_diff.py`, `tests/test_persistence_config.py`, additions to `tests/test_judge.py` + `tests/test_cli.py`, `tests/test_semantic.py`.

---

## Task 1: Record models

**Files:** Create `src/asc_metadata_verifier/persistence/__init__.py` (empty), `src/asc_metadata_verifier/persistence/models.py`; Test `tests/test_persistence_models.py`.

**Interfaces (Produces):** `RunRecord`, `RunSummary`, `FindingStatus`, `FindingDelta`, `RunDiff`.

- [ ] **Step 1: Failing tests** — `tests/test_persistence_models.py`:

```python
from asc_metadata_verifier.models import GateReport, RubricVerdict
from asc_metadata_verifier.persistence.models import (
    FindingDelta, FindingStatus, RunDiff, RunRecord, RunSummary,
)


def _report():
    return GateReport(status="WARN", guidelines_available=True,
                      verdicts=[RubricVerdict(dimension="placeholder_text", verdict="warn",
                                              severity="medium", confidence=0.7, rationale="r",
                                              locale="en-US", field="description")])


def test_runrecord_roundtrips_and_embeds_report():
    r = RunRecord(run_id="ab12", created_at="2026-08-10T12:00:00Z", app_id="123",
                  version=None, primary_locale="en-US", source="fastlane",
                  config_fingerprint="cfp", gate_status="WARN", report=_report(),
                  guideline_snapshot_hash="deadbeef")
    again = RunRecord.model_validate_json(r.model_dump_json())
    assert again.report.status == "WARN" and again.version is None
    assert again.gate_status == "WARN"


def test_run_summary_fields():
    s = RunSummary(run_id="ab12", created_at="t", app_id="123", version=None,
                   gate_status="WARN", source="fastlane")
    assert s.run_id == "ab12"


def test_rundiff_holds_deltas():
    d = RunDiff(status_a="PASS", status_b="BLOCK",
                deltas=[FindingDelta(locale="en-US", dimension="placeholder_text",
                                     field="description", kind=None,
                                     status=FindingStatus.new, severity_a=None, severity_b="high")])
    assert d.status_a == "PASS" and d.deltas[0].status is FindingStatus.new
```

- [ ] **Step 2: Run to fail** — `uv run pytest tests/test_persistence_models.py -q` → FAIL.

- [ ] **Step 3: Implement** `persistence/models.py`:

```python
"""Persistence record models. `created_at` is always PASSED IN (never generated
here) so the store stays deterministically testable."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from asc_metadata_verifier.models import GateReport


class RunRecord(BaseModel):
    run_id: str
    created_at: str  # ISO-8601, supplied by the caller
    app_id: str | None = None
    version: str | None = None  # not in AppMetadata today; future ASC-API populates it
    primary_locale: str | None = None
    source: str
    config_fingerprint: str
    gate_status: str
    report: GateReport
    guideline_snapshot_hash: str | None = None


class RunSummary(BaseModel):
    run_id: str
    created_at: str
    app_id: str | None = None
    version: str | None = None
    gate_status: str
    source: str


class FindingStatus(str, Enum):
    new = "new"
    resolved = "resolved"
    persisting = "persisting"
    severity_changed = "severity_changed"


class FindingDelta(BaseModel):
    locale: str
    dimension: str | None = None  # rubric verdicts
    field: str
    kind: str | None = None        # deterministic findings
    status: FindingStatus
    severity_a: str | None = None
    severity_b: str | None = None


class RunDiff(BaseModel):
    status_a: str
    status_b: str
    deltas: list[FindingDelta] = Field(default_factory=list)
```

- [ ] **Step 4: Pass + lint** — `uv run pytest tests/test_persistence_models.py -q`; `uv run ruff check .`.
- [ ] **Step 5: Commit** — `git commit -am "feat(persistence): run record + diff models"`

---

## Task 2: Cache keys

**Files:** Create `src/asc_metadata_verifier/persistence/cache.py`; Test `tests/test_cache.py`.

**Interfaces:** `PROMPT_VERSION: str`, `verdict_cache_key(prompt: str, model_name: str) -> str`, `snapshot_hash(text: str) -> str`, `VerdictCache` (adapter: `get(key)->RubricVerdict|None`, `put(key, verdict)`, wrapping a `Repository`).

> **Refinement from the spec (flag to reviewer/human):** the spec listed the key component-wise `(text, dimension, model, guideline_hash, prompt_version)`. This plan keys on the **built prompt string** (which already encodes dimension + all locale fields + grounding) plus `model_name` plus `PROMPT_VERSION` (a hash of the system prompt, which is NOT in the user prompt). This is a strictly *more complete* realization of the same "every verdict-affecting input is in the key, nothing else" invariant, and simpler.

- [ ] **Step 1: Failing tests** — `tests/test_cache.py`:

```python
from asc_metadata_verifier.persistence.cache import (
    PROMPT_VERSION, snapshot_hash, verdict_cache_key,
)


def test_key_is_stable_for_identical_inputs():
    assert verdict_cache_key("prompt A", "m1") == verdict_cache_key("prompt A", "m1")


def test_key_changes_on_prompt_or_model():
    base = verdict_cache_key("prompt A", "m1")
    assert verdict_cache_key("prompt B", "m1") != base   # prompt (text/dim/grounding) differs
    assert verdict_cache_key("prompt A", "m2") != base   # model differs


def test_prompt_version_is_nonempty_and_folds_in():
    assert PROMPT_VERSION and isinstance(PROMPT_VERSION, str)


def test_snapshot_hash_is_content_addressed():
    assert snapshot_hash("2.3 body") == snapshot_hash("2.3 body")
    assert snapshot_hash("x") != snapshot_hash("y")
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** `persistence/cache.py`:

```python
"""Content-hash keys for the verdict cache + guideline snapshots.

A cache HIT must be the identical computation. The key folds in `PROMPT_VERSION`
(a hash of the judge SYSTEM prompt, which is not part of the per-call user prompt),
the resolved model name, and the full built prompt string (which already encodes
the rubric dimension, every locale text field, and the grounding actually used).
Any change to any of those changes the key -> a miss -> a fresh judge run."""

from __future__ import annotations

import hashlib

from asc_metadata_verifier.judge import prompts

PROMPT_VERSION = hashlib.sha256(prompts.TEXT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def verdict_cache_key(prompt: str, model_name: str) -> str:
    payload = "\x00".join([PROMPT_VERSION, model_name, prompt])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def snapshot_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

(The `VerdictCache` adapter is added in Task 6 alongside the `Repository` it wraps.)

- [ ] **Step 4: Pass + lint.**
- [ ] **Step 5: Commit** — `git commit -am "feat(persistence): verdict-cache + snapshot content-hash keys"`

---

## Task 3: Repository protocol + SqliteRepository

**Files:** Create `src/asc_metadata_verifier/persistence/repository.py`, `src/asc_metadata_verifier/persistence/sqlite_repo.py`; Test `tests/test_sqlite_repo.py`.

**Interfaces (Produces):**
- `RepositoryError(Exception)`.
- `Repository` Protocol: `save_run(RunRecord)->None`, `get_run(str)->RunRecord|None`, `list_runs(app_id: str|None=None, limit: int=50)->list[RunSummary]` (newest first), `get_cached_verdict(key: str)->RubricVerdict|None`, `put_cached_verdict(key: str, verdict: RubricVerdict)->None`, `get_guideline_snapshot(hash: str)->str|None`, `put_guideline_snapshot(hash: str, text: str)->None`.
- `SqliteRepository(db_path: str | Path)` implementing it. Tables `runs(run_id PK, created_at, app_id, version, primary_locale, source, config_fingerprint, gate_status, guideline_snapshot_hash, report_json)`, `verdict_cache(key PK, verdict_json)`, `guideline_snapshots(hash PK, text)`, `schema_version(version INTEGER)`. Enable WAL. Create parent dir + tables on first open. `_migrate()` is a no-op at schema v1 (the seam for future bumps). `put_*` use `INSERT OR REPLACE` (snapshots/cache are content-addressed / idempotent). Store models via `model_dump_json()`, load via `model_validate_json()`.

- [ ] **Step 1: Failing tests** — `tests/test_sqlite_repo.py` (temp file; no network):

```python
from asc_metadata_verifier.models import GateReport, RubricVerdict
from asc_metadata_verifier.persistence.models import RunRecord
from asc_metadata_verifier.persistence.sqlite_repo import SqliteRepository


def _rec(run_id, app_id="123", status="WARN", created="2026-08-10T00:00:00Z"):
    return RunRecord(run_id=run_id, created_at=created, app_id=app_id, version=None,
                     primary_locale="en-US", source="fastlane", config_fingerprint="cfp",
                     gate_status=status, report=GateReport(status=status, guidelines_available=True))


def _repo(tmp_path):
    return SqliteRepository(tmp_path / "runs.db")


def test_save_get_roundtrip(tmp_path):
    repo = _repo(tmp_path)
    repo.save_run(_rec("aa"))
    got = repo.get_run("aa")
    assert got is not None and got.gate_status == "WARN" and got.report.status == "WARN"
    assert repo.get_run("missing") is None


def test_list_runs_newest_first_and_filtered(tmp_path):
    repo = _repo(tmp_path)
    repo.save_run(_rec("old", app_id="A", created="2026-08-01T00:00:00Z"))
    repo.save_run(_rec("new", app_id="A", created="2026-08-09T00:00:00Z"))
    repo.save_run(_rec("other", app_id="B", created="2026-08-10T00:00:00Z"))
    ids = [s.run_id for s in repo.list_runs(app_id="A")]
    assert ids == ["new", "old"]
    assert {s.run_id for s in repo.list_runs()} == {"old", "new", "other"}
    assert len(repo.list_runs(limit=1)) == 1


def test_verdict_cache_put_get(tmp_path):
    repo = _repo(tmp_path)
    v = RubricVerdict(dimension="placeholder_text", verdict="fail", severity="high",
                      confidence=0.9, rationale="r", locale="en-US", field="description")
    assert repo.get_cached_verdict("k") is None
    repo.put_cached_verdict("k", v)
    assert repo.get_cached_verdict("k").verdict == "fail"


def test_guideline_snapshot_dedup(tmp_path):
    repo = _repo(tmp_path)
    repo.put_guideline_snapshot("h1", "2.3 body")
    repo.put_guideline_snapshot("h1", "2.3 body")  # idempotent
    assert repo.get_guideline_snapshot("h1") == "2.3 body"
    assert repo.get_guideline_snapshot("nope") is None


def test_reopen_persists(tmp_path):
    _repo(tmp_path).save_run(_rec("aa"))
    assert SqliteRepository(tmp_path / "runs.db").get_run("aa") is not None
```

- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement** `repository.py` (Protocol + `RepositoryError`) and `sqlite_repo.py` per the interface above. Use `sqlite3` with `row_factory`; wrap connection errors in `RepositoryError` where they'd otherwise leak. One connection per `SqliteRepository` (or per-call `with sqlite3.connect(...)`); ensure tables exist in `__init__`.
- [ ] **Step 4: Pass + lint.**
- [ ] **Step 5: Commit** — `git commit -am "feat(persistence): Repository protocol + SqliteRepository (runs/cache/snapshots)"`

---

## Task 4: Cross-run diff

**Files:** Create `src/asc_metadata_verifier/persistence/diff.py`; Test `tests/test_diff.py`.

**Interfaces:** `diff_runs(a: RunRecord, b: RunRecord) -> RunDiff`; `render_diff_markdown(RunDiff)->str`; `render_diff_json(RunDiff)->str`.

**Semantics:** collect "present findings" from each run — a `RubricVerdict` counts iff `verdict in {"warn","fail"}` keyed `(locale, dimension, field)`; a `DeterministicFinding` always counts keyed `(locale, field, kind)` with `dimension=None`. For the union of keys: **new** (in b not a), **resolved** (in a not b), **persisting** (both, same severity), **severity_changed** (both, rubric severity differs; deterministic findings have no severity → never severity_changed). Emit `RunDiff(status_a=a.gate_status, status_b=b.gate_status, deltas=[…])` sorted stably.

- [ ] **Step 1: Failing tests** — `tests/test_diff.py`:

```python
from asc_metadata_verifier.models import DeterministicFinding, GateReport, RubricVerdict
from asc_metadata_verifier.persistence.diff import diff_runs, render_diff_markdown
from asc_metadata_verifier.persistence.models import FindingStatus, RunRecord


def _v(dim, verdict, sev, field="description", locale="en-US"):
    return RubricVerdict(dimension=dim, verdict=verdict, severity=sev, confidence=0.9,
                         rationale="r", locale=locale, field=field)


def _rec(run_id, status, verdicts=(), findings=()):
    return RunRecord(run_id=run_id, created_at="t", source="fastlane", config_fingerprint="c",
                     gate_status=status,
                     report=GateReport(status=status, guidelines_available=True,
                                       verdicts=list(verdicts), deterministic_findings=list(findings)))


def test_new_resolved_persisting_severity_changed():
    a = _rec("a", "WARN", verdicts=[_v("placeholder_text", "warn", "medium"),
                                    _v("misleading_claims", "fail", "high")])
    b = _rec("b", "BLOCK", verdicts=[_v("placeholder_text", "warn", "high"),   # severity changed
                                     _v("other_platform_mentions", "fail", "high")])  # new
    d = diff_runs(a, b)
    by = {(x.dimension, x.status) for x in d.deltas}
    assert ("other_platform_mentions", FindingStatus.new) in by
    assert ("misleading_claims", FindingStatus.resolved) in by
    assert ("placeholder_text", FindingStatus.severity_changed) in by
    assert d.status_a == "WARN" and d.status_b == "BLOCK"


def test_pass_verdicts_are_not_findings():
    a = _rec("a", "PASS", verdicts=[_v("placeholder_text", "pass", "low")])
    b = _rec("b", "PASS", verdicts=[_v("placeholder_text", "pass", "low")])
    assert diff_runs(a, b).deltas == []


def test_deterministic_findings_diffed_by_kind():
    fa = DeterministicFinding(locale="en-US", field="app_name", kind="over_limit", detail="d")
    d = diff_runs(_rec("a", "BLOCK", findings=[fa]), _rec("b", "PASS"))
    assert d.deltas[0].status is FindingStatus.resolved and d.deltas[0].kind == "over_limit"


def test_markdown_renders_sections():
    a = _rec("a", "PASS")
    b = _rec("b", "BLOCK", verdicts=[_v("placeholder_text", "fail", "high")])
    md = render_diff_markdown(diff_runs(a, b))
    assert "PASS" in md and "BLOCK" in md and "placeholder_text" in md
```

- [ ] **Step 2–5:** run-fail → implement `diff.py` → pass + lint → `git commit -am "feat(persistence): cross-run diff (new/resolved/persisting/severity)"`.

---

## Task 5: Backend config / registry

**Files:** Create `src/asc_metadata_verifier/persistence/config.py`; Test `tests/test_persistence_config.py`.

**Interfaces:** `resolve_repository(db_url: str | None) -> Repository | None` (None/empty → None); `BACKENDS: dict[str, Callable[[str], Repository]]` keyed by URL scheme; register `sqlite`. Accept `sqlite:///abs/path`, `sqlite://relative` — and a **bare path** (no scheme) → sqlite at that path. Unknown scheme → `RepositoryError` (actionable, secret-free — never echo the raw URL if it contains `@`). 

- [ ] **Step 1: Failing tests** — `tests/test_persistence_config.py`:

```python
import pytest

from asc_metadata_verifier.persistence.config import resolve_repository
from asc_metadata_verifier.persistence.repository import RepositoryError
from asc_metadata_verifier.persistence.sqlite_repo import SqliteRepository


def test_none_disables_persistence():
    assert resolve_repository(None) is None
    assert resolve_repository("") is None


def test_sqlite_url_and_bare_path(tmp_path):
    r1 = resolve_repository(f"sqlite:///{tmp_path/'a.db'}")
    r2 = resolve_repository(str(tmp_path / "b.db"))
    assert isinstance(r1, SqliteRepository) and isinstance(r2, SqliteRepository)


def test_unknown_scheme_raises_without_leaking_credentials():
    with pytest.raises(RepositoryError) as ei:
        resolve_repository("postgres://user:secretpw@host/db")
    assert "secretpw" not in str(ei.value)
```

- [ ] **Step 2–5:** run-fail → implement (`urllib.parse` for scheme; strip credentials before any message) → pass + lint → `git commit -am "feat(persistence): backend resolver + registry (sqlite default)"`.

---

## Task 6: Verdict-cache adapter + `judge_field` cache seam

**Files:** Modify `src/asc_metadata_verifier/persistence/cache.py` (add `VerdictCache`), `src/asc_metadata_verifier/judge/agent.py`; Test additions to `tests/test_cache.py`, `tests/test_judge.py`.

**Interfaces:**
- `VerdictCache(repo: Repository)` with `get(key)->RubricVerdict|None` (delegates `repo.get_cached_verdict`) and `put(key, verdict)` (delegates `repo.put_cached_verdict`).
- `judge_field(meta, guidelines, dimensions, model=None, cache=None)` — **`cache=None` → today's behavior, untouched.** When `cache` is given (any object with `.get`/`.put`), per (locale, dimension): build the prompt as today, compute `key = verdict_cache_key(prompt, model_name)` where `model_name = str(agent.model)`; on `cache.get(key)` hit, reuse that verdict (re-stamp authoritative `locale`/`dimension` defensively, no model call); on miss, run the agent as today, then `cache.put(key, verdict)`.

- [ ] **Step 1: Failing tests** — add to `tests/test_judge.py` (reuse its `_model(factory)` `FunctionModel` helper):

```python
def test_cache_hit_skips_the_model_call():
    calls = {"n": 0}
    def factory(_t):
        calls["n"] += 1
        return RubricVerdict(dimension="x", verdict="fail", severity="high", confidence=0.9,
                             rationale="r", offending_quote="q", locale="x", field="description")

    class DictCache:
        def __init__(self): self.d = {}
        def get(self, k): return self.d.get(k)
        def put(self, k, v): self.d[k] = v

    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="Lorem ipsum")])
    g = Guidelines(available=True, text="2.3", sections={"2.3": "2.3"}, source="t")
    cache = DictCache()
    model = _model(factory)
    v1 = judge_field(meta, g, [_dim("placeholder_text")], model=model, cache=cache)
    v2 = judge_field(meta, g, [_dim("placeholder_text")], model=model, cache=cache)
    assert calls["n"] == 1                       # second run served from cache
    assert v1[0].verdict == v2[0].verdict == "fail"
    assert v2[0].locale == "en-US" and v2[0].dimension == "placeholder_text"


def test_cache_miss_when_grounding_changes():
    calls = {"n": 0}
    def factory(_t):
        calls["n"] += 1
        return RubricVerdict(dimension="x", verdict="pass", severity="low", confidence=0.5,
                             rationale="r", locale="x", field="description")

    class DictCache:
        def __init__(self): self.d = {}
        def get(self, k): return self.d.get(k)
        def put(self, k, v): self.d[k] = v

    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="x")])
    cache = DictCache()
    model = _model(factory)
    judge_field(meta, Guidelines(available=True, text="A", sections={"2.3": "A"}, source="t"),
                [_dim("placeholder_text")], model=model, cache=cache)
    judge_field(meta, Guidelines(available=True, text="B", sections={"2.3": "B"}, source="t"),
                [_dim("placeholder_text")], model=model, cache=cache)
    assert calls["n"] == 2                        # different grounding -> different prompt -> miss
```

- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement** the `VerdictCache` adapter in `cache.py` and thread the optional `cache` seam into `judge_field` per the interface (guard everything on `cache is not None`; do NOT change the no-cache path). Confirm existing `tests/test_judge.py` cases (which call `judge_field` without `cache`) still pass unchanged.
- [ ] **Step 4: Full suite + lint** — `uv run pytest -q` (existing judge tests green) ; ruff.
- [ ] **Step 5: Commit** — `git commit -am "feat(persistence): VerdictCache adapter + optional judge_field cache seam"`

---

## Task 7: CLI — default-command group, history/diff, --db/--cache/--save wiring

**Files:** Modify `src/asc_metadata_verifier/cli.py`, `.gitignore`; Test additions to `tests/test_cli.py`.

**THE BACKWARD-COMPAT REQUIREMENT (hard):** `asc-verify <fastlane-path>` with **no subcommand** must keep working; every existing `tests/test_cli.py`/`tests/test_e2e.py` invocation (`runner.invoke(cli.app, [FIXTURE_ROOT, ...])`) passes **unchanged**. Adding `history`/`diff` subcommands must not require a `verify` token for the bare form.

**Mechanism:** a default-command click group. Provide this `DefaultCommandGroup` and make the typer app use it:

```python
import click

class DefaultCommandGroup(click.Group):
    """Route a bare invocation (first token is not a known subcommand and not an
    option/flag) to the default `verify` command, so `asc-verify <path>` keeps working."""
    default_command = "verify"

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = [self.default_command, *args]
        return super().parse_args(ctx, args)

    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            return super().resolve_command(ctx, [self.default_command, *args])
```

> **Task-owner note (verify empirically, first thing):** confirm how to attach a custom group class in the installed **typer 0.27.1** — e.g. `typer.Typer(cls=DefaultCommandGroup)` if supported, else obtain the click command via `typer.main.get_command(app)` and set its `cls`/rebuild. Whichever the installed typer supports, the acceptance gate is fixed: `runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision"])` works with NO `verify` token AND `runner.invoke(cli.app, ["history", ...])` dispatches to the subcommand. If neither wiring works cleanly, STOP and report — do not silently change the bare-form contract.

**New surface:**
- `verify` gains: `--db <url>` (Path/str), `--cache/--no-cache` (default `--no-cache`), `--no-save`. When `--db` resolves a repo: build a `VerdictCache(repo)` and pass it to the judge path **only when `--cache`**; after producing the report, unless `--no-save`, persist — snapshot the guideline text (`snapshot_hash` → `put_guideline_snapshot`) and `save_run(RunRecord(...))` with `created_at` = an ISO timestamp the CLI computes now, `run_id` = a short uuid, `config_fingerprint` = a stable hash of `(fail_on, judge model/jury, consensus)`. **Report + exit code are produced FIRST; a persistence exception becomes a stderr `WARNING:` and never changes the exit code or hides the gate.**
- `history [--db][--app-id][--limit]` → `repo.list_runs` → a plain table on stdout.
- `diff <run_a> <run_b> [--db][--format md|json]` → `get_run` both (missing id → exit 2 actionable) → `diff_runs` → render.
- `RepositoryError` caught in each command → `Error: {exc}` + exit 2, no traceback.
- `.gitignore`: add `.asc-verify/`.

`run_verify` gains `cache=None` and passes it into `judge_field(...)` (jury path caching is out of scope — the single-judge path is the cache consumer for B).

- [ ] **Step 1: Failing tests** — add to `tests/test_cli.py`:

```python
class TestPersistence:
    def test_bare_verify_still_works_with_no_subcommand(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision"])   # NO 'verify' token
        assert result.exit_code == 0, result.output

    def test_db_saves_and_history_lists(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)
        db = f"sqlite:///{tmp_path/'runs.db'}"
        assert runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--db", db]).exit_code == 0
        out = runner.invoke(cli.app, ["history", "--db", db])
        assert out.exit_code == 0 and ("PASS" in out.output or "WARN" in out.output)

    def test_diff_between_two_saved_runs(self, tmp_path, monkeypatch):
        # save two runs, capture their ids from history, diff them; assert exit 0 + a status line
        ...

    def test_bad_db_scheme_exits_2_no_traceback(self):
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--db", "mysql://h/d", "--dry-run"])
        assert result.exit_code == 2 and "Traceback" not in result.output
```

(Flesh out `test_diff_between_two_saved_runs` using the run ids `history` prints, or a `--format json` on history if added.)

- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement** the group + subcommands + wiring. Keep all module-level monkeypatch seams (`cli.get_guidelines`, `cli.judge_field`, `cli.judge_screenshots`) intact. Add `cli.resolve_repository` at module level (monkeypatchable).
- [ ] **Step 4: FULL suite + lint** — every pre-existing CLI/e2e test green; ruff clean.
- [ ] **Step 5: Commit** — `git commit -am "feat(persistence): CLI default-command group + history/diff + --db/--cache/--save"`

---

## Task 8: Semantic protocols + stub (Phase 2, offline)

**Files:** Create `src/asc_metadata_verifier/persistence/semantic.py`; Test `tests/test_semantic.py`.

**Interfaces:** `Embedder` Protocol (`embed(texts: list[str]) -> list[list[float]]`); `StubEmbedder` (deterministic: hash each text → fixed-length float vector, offline); `SemanticIndex` Protocol (`add(items: list[tuple[str, dict]])` where each item is `(text, metadata)`; `query(text: str, k: int) -> list[dict]`); `InMemoryIndex(embedder)` (cosine over stored vectors — the offline default used by tests and when no Chroma is configured). No default embedder is exported for real use.

- [ ] **Step 1: Failing tests** — `tests/test_semantic.py`:

```python
from asc_metadata_verifier.persistence.semantic import InMemoryIndex, StubEmbedder


def test_stub_embedder_deterministic_fixed_dim():
    e = StubEmbedder()
    assert e.embed(["a"]) == e.embed(["a"])
    assert len(e.embed(["a"])[0]) == len(e.embed(["bb"])[0])


def test_in_memory_index_returns_nearest():
    idx = InMemoryIndex(StubEmbedder())
    idx.add([("placeholder lorem ipsum", {"run_id": "r1", "dimension": "placeholder_text"}),
             ("also available on android", {"run_id": "r2", "dimension": "other_platform_mentions"})])
    hits = idx.query("lorem ipsum placeholder", k=1)
    assert hits and hits[0]["run_id"] == "r1"
```

- [ ] **Step 2–5:** run-fail → implement (pure Python cosine; no numpy required, or numpy only if already available — keep dependency-free) → pass + lint → `git commit -am "feat(persistence): semantic Embedder/SemanticIndex protocols + offline stub"`.

---

## Task 9: ChromaIndex + `similar` command + `[semantic]` extra

**Files:** Modify `src/asc_metadata_verifier/persistence/semantic.py` (add `ChromaIndex`), `src/asc_metadata_verifier/cli.py` (add `similar`), `pyproject.toml`; Test additions to `tests/test_semantic.py`, `tests/test_cli.py`.

**Interfaces:** `ChromaIndex(embedder, path)` implementing `SemanticIndex` over `chromadb` (imported lazily inside the class so the core install never imports it). `similar "<text>" [--db][-k]` CLI: requires a configured semantic index + embedder; when unconfigured (default), prints a clean `Error: semantic recall not configured (install the 'semantic' extra and configure an embedder)` and exits 2 — never a traceback. `pyproject.toml`: `[project.optional-dependencies] semantic = ["chromadb>=0.5"]`.

- [ ] **Step 1: Failing tests** — add to `tests/test_semantic.py` and `tests/test_cli.py`:

```python
# test_semantic.py
def test_chroma_index_gated_behind_dependency():
    import pytest
    chromadb = pytest.importorskip("chromadb")  # skips cleanly when not installed
    from asc_metadata_verifier.persistence.semantic import ChromaIndex, StubEmbedder
    idx = ChromaIndex(StubEmbedder(), path=None)  # in-memory chroma
    idx.add([("lorem ipsum", {"run_id": "r1"})])
    assert idx.query("lorem", k=1)[0]["run_id"] == "r1"

# test_cli.py
class TestSimilar:
    def test_similar_without_config_errors_cleanly(self):
        result = runner.invoke(cli.app, ["similar", "lorem ipsum"])
        assert result.exit_code == 2 and "Traceback" not in result.output
        assert "semantic recall not configured" in result.output.lower()
```

- [ ] **Step 2–5:** run-fail → implement (lazy `import chromadb`; `similar` wiring) → `uv run pytest -q` (chroma test SKIPS if absent — do NOT install chromadb into the dev env) + ruff → `git commit -am "feat(persistence): ChromaIndex (optional) + similar command + [semantic] extra"`.

---

## Task 10: Documentation

**Files:** Modify `README.md`, `BUILD_LOG.md`.

- [ ] **Step 1: README** — add a "Persistence (optional)" section: opt-in via `--db sqlite:///runs.db`; `history` / `diff` / `--cache` / `--no-save`; the repository-pattern note (SQLite default, pluggable); semantic recall as an opt-in `[semantic]` extra with a bring-your-own embedder; and the honest status — default (no `--db`) is byte-identical + offline + zero new deps; the verdict cache only ever returns an identical prior computation; semantic is untested against a real embedder/Chroma in CI (stub-tested).
- [ ] **Step 2: BUILD_LOG** — append a v2/persistence entry: the design decisions (opt-in/zero-new-dep default; prompt-based cache key + `PROMPT_VERSION`; default-command group for CLI backward-compat; report-first-then-save so a persistence failure never hides the gate; semantic BYO-embedder / no bundled model); which tasks took fix rounds; honest open items (`ChromaIndex` + a real embedder not exercised in CI; `version`/`config_fingerprint` fields; jury-path caching deferred).
- [ ] **Step 3: Full suite + lint** — `uv run pytest -q`, `uv run ruff check .`.
- [ ] **Step 4: Commit** — `git commit -am "docs(persistence): README section + honest BUILD_LOG"`

---

## Self-Review (author checklist — completed)

**Spec coverage:** history (T3 `list_runs` + T7 `history`) · cross-run diff (T4 + T7 `diff`) · verdict cache (T2 keys, T6 seam, T7 `--cache`) · guideline snapshots (T3 table, T7 save) · semantic recall (T8 protocols/stub, T9 Chroma + `similar`) · repository pattern + registry (T3, T5) · CLI backward-compat (T7 default-command group) · offline/opt-in default (every task's no-`--db` path) · secrets-by-reference (T5) · report-first-then-save (T7). All spec sections map to a task.

**Placeholder scan:** two tests are marked to flesh out (`test_diff_between_two_saved_runs`, and the `similar` skip) — both have their assertions/approach specified, not left blank. The one genuinely-unknown external API (typer 0.27.1 custom-group wiring) is handled by an explicit verify-first task-owner note with a fixed acceptance gate, not a guess.

**Type consistency:** `RunRecord`/`RunSummary`/`RunDiff`/`FindingDelta`/`FindingStatus` (T1) used identically in T3/T4/T7. `Repository` protocol methods (T3) match `VerdictCache` (T6), `resolve_repository` (T5), and CLI wiring (T7). `verdict_cache_key(prompt, model_name)` consistent T2↔T6. `judge_field(..., cache=None)` consistent T6↔T7. `SemanticIndex.add/query` consistent T8↔T9.

**Refinements from the spec (flag at handoff):** (1) cache key is prompt-based + `PROMPT_VERSION`=system-prompt-hash (strictly ⊇ the spec's component list); (2) `RunRecord.version` is `None`-for-now (`AppMetadata` has no version field yet). Both preserve the spec's intent.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-10-persistence.md`.** Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, spec+quality review gate after each, whole-branch review at the end (same method that built v1 + the jury).

**2. Inline Execution** — execute tasks in this session with checkpoints.

**Which approach?**
