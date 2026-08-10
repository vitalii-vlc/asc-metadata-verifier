# Persistence — Design Spec (v2, sub-project B)

> Pre-registration commit — scope + design fixed **before** any feature code
> (honest-velocity method, mirroring v1 and the jury sub-project). Date: 2026-08-10.
>
> Second of five v2 sub-projects. The others — code analyzer (C), pages analyzer
> (D), HTML report generator (E) — each get their own spec → plan → build cycle and
> are **out of scope here**. Persistence is built second because history + diffing
> are the "better experience" the tool most obviously lacks, and because the store
> it defines is what sub-project E's HTML report will later read from.

**Goal:** add an **opt-in** persistence layer so the verifier remembers runs —
giving run **history**, **cross-run diff** (what findings are new / resolved /
persisting between two runs), a **content-hash verdict cache** (skip re-judging
unchanged metadata), **guideline snapshots** (old runs stay reproducible), and
optional **semantic recall** over past findings — all behind a **repository
pattern** so the backend is swappable, with SQLite (stdlib) as the default.

**Architecture (one line):** a `Repository` protocol (structured store: runs +
verdict cache + guideline snapshots) with a stdlib-`sqlite3` default and a
pluggable backend registry, plus a separate opt-in `SemanticIndex` protocol
(Chroma impl, bring-your-own `Embedder`); the CLI gains `history`/`diff`/`similar`
subcommands while `asc-verify <path>` keeps working unchanged.

**Tech stack:** Python 3.11 (uv) · `sqlite3` (stdlib — **no new core dependency**) ·
pydantic v2 (record models) · typer (CLI subcommands) · hashlib (content
addressing / cache keys). Optional extra `semantic`: `chromadb` (vector index) +
a **bring-your-own** embedder (no embedder is bundled).

---

## Global constraints
- **Opt-in / additive / backward compatible (hard):** with no `--db` and no
  persistence config, behavior is **byte-identical to today**, does **no** disk or
  network I/O for persistence, and pulls **zero new dependencies**. Every existing
  test — including `asc-verify <fastlane-path>` invoked with no subcommand — passes
  unchanged.
- **Cache correctness is an honesty invariant:** a verdict-cache **hit** must be
  provably the *identical* inputs — same field text, rubric dimension, judge model,
  guideline snapshot, and prompt version. Any difference is a **miss**. The cache
  only avoids recomputing an identical verdict; it never alters a verdict's content.
  `--no-cache` forces fresh judging. This is tested (a changed model / prompt /
  grounding produces a miss).
- **Offline-safe:** the persistence layer is fully testable with a temp SQLite file
  and the deterministic stub embedder — no network, no key. The default install has
  no `chromadb`, no embedder, and downloads nothing. Semantic recall is opt-in.
- **Secrets by reference:** a credentialed backend URL (e.g. Postgres
  `postgres://user:pass@host/db`) is never logged or echoed in errors; same posture
  as the ASC-API `.p8` / jury `api_key_env` handling.
- **No fabrication:** history/diff/`similar` report only what is actually stored; a
  cache hit is never presented as a fresh judgement and vice-versa.
- **Style:** ruff (`E,F,I,UP,B`), line-length 100, target py311. Match v1/v2-A
  module + docstring conventions.

## Non-goals (this sub-project)
- No server, daemon, or long-running process; no multi-writer concurrency beyond
  SQLite WAL.
- No web UI or HTML rendering — that is sub-project E, which will later *read* this
  store.
- No cross-DB schema auto-migration tooling beyond the SQLite schema-version bump.
- No bundled embedding model and no default embedder (bring-your-own).
- No automatic pruning / retention policy (a `history --limit` view only; deletion
  is future work).

---

## Data flow
```
                          ┌─────────────── no --db: today's path, untouched (offline, no I/O) ──────────────┐
source ─▶ run_verify ─▶ GateReport ─▶ render/exit
                          │  --db set (persistence on):
                          │    --cache: per (locale,dimension) judge call, look up
                          │      verdict_cache_key(text, dim, model, guideline_snapshot_hash, prompt_ver)
                          │        hit  → reuse the stored RubricVerdict (no LLM call)
                          │        miss → judge, then put(verdict) under that key
                          │    store guideline snapshot by content-hash (dedup)
                          │    save RunRecord(GateReport + config fingerprint + snapshot ref)
                          ▼
                       Repository (SqliteRepository default)
history  ─▶ list_runs(app_id?, limit) ─▶ table
diff a b ─▶ get_run(a), get_run(b) ─▶ diff_runs ─▶ NEW / RESOLVED / PERSISTING / SEVERITY_CHANGED + status delta
similar  ─▶ Embedder.embed(text) ─▶ SemanticIndex.query(k) ─▶ similar past findings         [Phase 2, opt-in]
```

## Components (module map)

### New package `persistence/`
- **`models.py`** — record types (all pydantic):
  - `RunRecord`: `run_id: str` (short content/uuid id), `created_at: str` (ISO,
    passed in — never generated implicitly in a testable seam), `app_id: str | None`,
    `version: str | None`, `primary_locale: str | None`, `source: str`
    (`fastlane|yaml|asc-api`), `config_fingerprint: str` (stable hash of fail_on +
    judge model(s) + consensus policy + jury-set), `gate_status: str`,
    `report: GateReport` (embedded), `guideline_snapshot_hash: str | None`.
  - `RunSummary`: the list-view projection (`run_id`, `created_at`, `app_id`,
    `version`, `gate_status`, `source`).
  - `FindingKey` + `RunDiff`: the diff result — lists of NEW / RESOLVED / PERSISTING
    / SEVERITY_CHANGED finding keys plus the `(status_a, status_b)` gate delta.
- **`repository.py`** — the **`Repository` Protocol** (structured store) and
  `RepositoryError(Exception)`:
  - `save_run(record: RunRecord) -> None`
  - `get_run(run_id: str) -> RunRecord | None`
  - `list_runs(app_id: str | None = None, limit: int = 50) -> list[RunSummary]`
    (newest first)
  - `get_cached_verdict(key: str) -> RubricVerdict | None`
  - `put_cached_verdict(key: str, verdict: RubricVerdict) -> None`
  - `get_guideline_snapshot(snapshot_hash: str) -> str | None`
  - `put_guideline_snapshot(snapshot_hash: str, text: str) -> None`
- **`sqlite_repo.py`** — **`SqliteRepository`** (default; stdlib `sqlite3`).
  Tables: `runs` (metadata columns + `report_json`), `verdict_cache`
  (`key` PK → `verdict_json`), `guideline_snapshots` (`hash` PK → `text`,
  content-addressed → automatic dedup across runs), `schema_version` (single row).
  `WAL` journal mode; `create_if_missing`; a `_migrate()` that is a no-op at v1 but
  is the seam for future schema bumps. Opens/creates the DB file lazily.
- **`cache.py`** — `verdict_cache_key(text, dimension_id, model_name,
  guideline_snapshot_hash, prompt_version) -> str` (sha256 hex over a canonical
  joined string). `PROMPT_VERSION` constant (bumped whenever the judge system
  prompt changes) is folded in, so a prompt change invalidates the cache.
  `snapshot_hash(text) -> str` (sha256) for guideline content addressing.
- **`diff.py`** — `diff_runs(a: RunRecord, b: RunRecord) -> RunDiff`, a pure
  function. Matches rubric verdicts by `(locale, dimension, field)` and
  deterministic findings by `(locale, field, kind)`; a finding "present" iff its
  verdict is `warn`/`fail` (or the deterministic finding exists). Classifies each
  key: **NEW** (present in b, not a), **RESOLVED** (present in a, not b),
  **PERSISTING** (both), **SEVERITY_CHANGED** (both present, severity differs).
  Plus the gate-status delta `(a.gate_status, b.gate_status)`. Rendering to
  markdown / JSON lives here (`render_diff_markdown`, `render_diff_json`).
- **`config.py`** — `resolve_repository(db_url: str | None) -> Repository | None`.
  `None`/empty → `None` (persistence off). `sqlite:///path` or a bare path →
  `SqliteRepository`. A `BACKENDS: dict[str, Callable]` registry maps a URL scheme
  to a factory so another DB registers itself without touching the CLI. Unknown
  scheme / unreadable path → `RepositoryError` with an actionable, secret-free
  message.
- **`semantic.py`** *(Phase 2)* — `Embedder` Protocol (`embed(texts: list[str]) ->
  list[list[float]]`); `StubEmbedder` (deterministic hash→fixed-dim vector, offline,
  for tests); `SemanticIndex` Protocol (`add(items)`, `query(text, k) -> list[hit]`);
  `ChromaIndex` (optional `chromadb`). **No default embedder** — the user configures
  one; without it, `similar` reports a clean "semantic recall not configured" error.

### Changed
- **`cli.py`** — restructured from a single `verify` command into a typer app with a
  **`@app.callback(invoke_without_command=True)`** so `asc-verify <path> …` still runs
  `verify` when no subcommand is given (backward-compat, see below), plus new
  subcommands `history`, `diff`, `similar`. `verify` gains `--db`, `--cache/--no-cache`
  (default no-cache), `--no-save`. Persistence is threaded as a resolved
  `Repository | None`; when set and not `--no-save`, the run is saved. `RepositoryError`
  is caught like `IngestError`/`JudgeConfigError` (message + exit 2, no traceback).
- **`judge/agent.py`** (+ `judge/vision.py`) — `judge_field` gains an **optional**
  `cache` seam: `judge_field(..., cache=None, cache_ctx=None)` where `cache` is a
  small callable/adapter that, given the cache key inputs, returns a cached
  `RubricVerdict` or `None` and stores new ones. Default `None` → today's behavior,
  no caching, untouched. (The panel/`judge_screenshots` may participate later; text
  judge is the first cache consumer.)
- **`pyproject.toml`** — no core dependency change. Add
  `[project.optional-dependencies] semantic = ["chromadb>=0.5"]`.

## CLI backward-compatibility (must-hold)
`asc-verify <fastlane-path>` — with **no subcommand** — must keep working exactly
as today (the bundled `app-store-review-gate` skill and every `tests/test_cli.py` /
`tests/test_e2e.py` case invoke it that way). The restructure uses a typer callback
with `invoke_without_command=True`: when no subcommand is present, the callback runs
the `verify` pipeline with the same options; the named subcommands (`history`,
`diff`, `similar`) are additive. Existing tests are **not** rewritten to insert a
`verify` token. A test asserting this exact compat is part of Phase 1.

## The verdict cache (correctness-critical)
- **Key:** `sha256( text ∥ dimension_id ∥ model_name ∥ guideline_snapshot_hash ∥
  PROMPT_VERSION )`. Every input that can change a verdict is in the key; nothing
  else is. `guideline_snapshot_hash` is the sha256 of the exact grounding text used
  (empty-string hash when grounding was unavailable), so a guidelines change is a
  miss. `PROMPT_VERSION` is a module constant bumped on any judge-prompt edit.
- **Semantics:** on a hit, the stored `RubricVerdict` is reused verbatim (its
  authoritative `locale`/`dimension` re-stamped as today); on a miss, judge then
  store. `--cache` enables it; default is **off** so `verify` behavior is unchanged
  unless asked. `--no-cache` explicitly disables even when a store is configured.
- **Never a correctness hazard:** because the key captures model + prompt + grounding
  + text + dimension, a hit is the same computation. If any of those move, it is a
  miss and the judge runs. Tested per component.

## Semantic recall (Phase 2, opt-in, bring-your-own embedder)
- Enabled only when the user configures a `SemanticIndex` (Chroma) **and** an
  `Embedder`. Default install ships neither `chromadb` nor an embedder and downloads
  nothing.
- `similar "<text>" [-k N]` embeds the query and returns the nearest stored findings
  (finding text + which past run + verdict). Indexing happens at save time when
  semantic is configured (findings' offending quotes / rationales are embedded).
- `StubEmbedder` (deterministic, offline) backs the unit tests of the query/index
  logic; `ChromaIndex` is exercised only behind a dependency gate (skipped when
  `chromadb` is absent) — CI never downloads a model.

## Error handling
- Bad `--db` (unknown scheme, unwritable path) → `RepositoryError` → CLI message +
  exit 2, no traceback, no secret echo.
- `diff <a> <b>` with a missing run id → actionable "run <id> not found" (exit 2).
- `similar` without semantic configured → clean "semantic recall not configured
  (install the `semantic` extra and configure an embedder)".
- A persistence failure during `verify` (e.g. disk error saving the run) must **not**
  discard the gate result: the report + exit code are produced first; a save failure
  is surfaced as a stderr warning, never a swallowed error and never a crash that
  hides the gate decision.

## Testing
- **SqliteRepository:** save/get/list round-trip; `list_runs` newest-first + `app_id`
  filter + `limit`; verdict-cache hit/miss on each key component (text, dimension,
  model, guideline hash, prompt version); guideline-snapshot dedup; schema-version
  migration no-op; temp-file isolation (no shared global state).
- **cache.py:** the key changes iff a component changes; identical inputs → identical
  key.
- **diff.py:** NEW / RESOLVED / PERSISTING / SEVERITY_CHANGED classification and the
  gate-status delta over synthetic `RunRecord`s (verdicts + deterministic findings).
- **CLI:** `verify --db <tmp>` saves; `history` lists it; `diff a b` renders the diff;
  `--cache` skips a second judge call on unchanged input (assert the injected judge is
  not re-invoked) and re-judges when the model/prompt/grounding changes; the
  **no-subcommand backward-compat** case (`asc-verify <path>`) still works; bad `--db`
  → exit 2 no traceback. All offline (temp sqlite, injected model, stub guidelines).
- **Backward-compat:** the full pre-existing suite passes unchanged.
- **Semantic (Phase 2):** `StubEmbedder` + an in-memory/stub `SemanticIndex` cover the
  query logic; `ChromaIndex` behind a `pytest.importorskip("chromadb")` gate — no
  downloads in CI.

## Repo & naming
- Same repo: `~/Projects/asc-metadata-verifier`. Branch: `feat/persistence`.
- Package: `asc_metadata_verifier.persistence`. Default DB path when `--db` is bare:
  `.asc-verify/history.db` (git-ignored; add to `.gitignore`).

## Phasing
- **Phase 1 (core, zero new deps):** `models` · `repository` · `sqlite_repo` ·
  `cache` · `diff` · `config` · the `judge_field` cache seam · CLI restructure +
  `verify --db/--cache/--no-save` + `history` + `diff`.
- **Phase 2 (optional `semantic` extra):** `Embedder` protocol + `StubEmbedder` ·
  `SemanticIndex` protocol + `ChromaIndex` · save-time indexing · `similar` command ·
  the `[semantic]` optional dependency.

## Definition of done
`asc-verify verify <fastlane> --db sqlite:///runs.db` saves a run; `asc-verify
history` lists it (newest first, filterable by app); `asc-verify diff <a> <b>` shows
NEW / RESOLVED / PERSISTING findings + the status delta; `--cache` demonstrably skips
re-judging unchanged metadata and re-judges on a model/prompt/grounding change;
**no `--db` → byte-identical, offline, zero new deps**, and `asc-verify <path>` (no
subcommand) still works; semantic recall works with a bring-your-own embedder +
Chroma (stub-tested) and is cleanly disabled otherwise; unit + offline CLI tests
green with no network/keys; `.gitignore` updated; README + honest BUILD_LOG shipped.

## Pre-registration (honest estimate — to confirm before feature code)
**Estimate: 3–4 working-days part-time.** Split: SqliteRepository + models + cache +
diff (the bulk, all offline-testable) ~1.5–2; CLI restructure with the
no-subcommand backward-compat callback + `history`/`diff` wiring + the cache seam
~1–1.5; semantic Phase 2 (protocols + stub + Chroma behind the extra + `similar`)
~0.5–1. Top risks: (1) the typer callback that preserves `asc-verify <path>` while
adding subcommands without breaking existing tests; (2) getting the verdict-cache
key to capture *everything* that affects a verdict (a stale hit would be a silent
correctness/honesty bug); (3) `chromadb` optional-dependency isolation so the core
install and CI never pull it or download a model; (4) threading the cache seam
through `judge_field` without changing default (no-cache) behavior.

## Open questions
- None blocking. Default DB path, cache-key composition, and the backward-compat
  mechanism are all specified above rather than deferred.
