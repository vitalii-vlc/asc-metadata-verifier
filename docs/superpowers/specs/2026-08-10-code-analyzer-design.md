# Code Analyzer — Design Spec (v2, sub-project C)

> Pre-registration commit — scope + design fixed **before** any feature code
> (honest-velocity method, mirroring v1, the jury, and persistence). Date: 2026-08-10.
>
> Third of five v2 sub-projects. The others — pages analyzer (D) and HTML report
> generator (E) — each get their own spec → plan → build cycle and are **out of
> scope here**. C analyzes the app's **source code and config manifests** for App
> Store rejection risk; the metadata analyzer (v1) and the jury (A) already cover
> App Store Connect *metadata*.

**Goal:** add an **additive** `code` capability that runs **deep AST-level static
analysis** over a local Apple app project (Swift/Obj-C source + `Info.plist` +
`*.entitlements` + `PrivacyInfo.xcprivacy`), flags a **curated, high-confidence
set of rejection-risk findings** — each anchored to `file:line` + evidence and
mapped to a specific App Store Review Guideline section — and rolls them into the
same **PASS/WARN/BLOCK** gate. An **opt-in** jury layer judges borderline cases
the AST can't decide, grounded in the live guidelines.

**Architecture (one line):** a new `code/` package — offline project loader →
pluggable `SourceParser` (tree-sitter default, optional SwiftSyntax backend,
strategy pattern) → a `Rule` registry producing `CodeFinding`s → the existing
gate rollup; plus an opt-in `jury.py` that escalates interpretive findings to the
existing `JudgePanel`. A standalone `asc-verify code <path>` command yields a
`CodeReport`; `asc-verify verify <meta> --code <path>` folds `CodeFinding`s into
the unified `GateReport`.

**Tech stack:** Python 3.11 (uv) · pydantic v2 (finding/report models) · typer
(CLI) · stdlib `plistlib`/`pathlib` (manifest parsing, project walk — **no new
core dependency**). Optional extra `code`: `tree-sitter` + `tree-sitter-language-pack`
(Swift + Obj-C grammars, offline). Optional extra `code-swift`: SwiftSyntax
subprocess backend (needs a Swift toolchain). Jury layer reuses the existing
`judge/` panel (opt-in, API keys by env-var reference).

---

## Global constraints

- **Additive / backward compatible (hard):** with no `code` command and no
  `--code` flag, behavior is **byte-identical to today** — plain `verify`,
  `history`, `diff`, `similar`, and bare `asc-verify <path>` all pass unchanged,
  do no extra I/O, and pull **zero new core dependencies**. tree-sitter lives
  behind the `[code]` extra; SwiftSyntax behind `[code-swift]`; both are
  lazy-imported.
- **Offline by default (hard):** `asc-verify code <path>` with no `--jury` makes
  **zero network calls**. The static analyzer never touches the network. Only the
  opt-in jury layer may, and its guideline grounding reuses the existing
  session cache, degrading to `available=False` (never fabricated) when offline.
- **Never fabricate (honesty invariant):** every `CodeFinding` is anchored to a
  real `file:line` and an `evidence` quote a human can open and verify. A missing
  manifest, an unavailable parser backend, or an absent Swift toolchain each
  produce a **factual state**, never a guess. Jury-sourced items are tagged
  `source="jury"` and carry the full vote record — LLM judgment is never
  presented as deterministic fact.
- **Curated, not exhaustive (honesty invariant):** the rule catalog and the
  `private-api-symbol` / `required-reason-api-undeclared` denylists are curated
  and **documented as non-exhaustive**. The tool never claims to detect every
  private API or required-reason call. False negatives are expected and stated
  per rule.
- **Deterministic static core:** identical project input → identical
  `CodeFinding`s (ordering included). The static analyzer contains no randomness
  and no LLM calls.
- **Secrets by reference:** jury mode reuses the env-var-ref judges config; no
  key material appears in output or errors.

---

## Component 1 — Project loader (`code/project.py`)

Offline filesystem walk of a project root. Discovers, without building anything:

- **Sources:** `*.swift`, `*.m`, `*.h` (skips `Pods/`, `Carthage/`, `.build/`,
  `DerivedData/`, `*.xcassets`, and hidden dirs by default).
- **Manifests:** every `Info.plist`, every `*.entitlements`, every
  `PrivacyInfo.xcprivacy`. Parsed with stdlib `plistlib` (both XML and binary
  plists). A malformed plist yields a factual `parse_error` note on the artifact,
  not an exception that aborts the run.

Produces a `ProjectModel`:

```
ProjectModel:
  root: str
  sources: list[SourceFile]        # path, language("swift"|"objc"), text (lazy)
  info_plists: list[PlistArtifact] # path, data: dict | None, parse_error: str | None
  entitlements: list[PlistArtifact]
  privacy_manifests: list[PlistArtifact]
```

The loader is pure and offline; it does not parse ASTs (that is the parser's job)
— it only locates files and reads the plist key/value trees rules need for
cross-artifact correlation.

---

## Component 2 — Parser strategy (`code/parser.py` + `code/backends/`)

`SourceParser` protocol:

```
class SourceParser(Protocol):
    backend_name: str
    def available(self) -> bool: ...
    def parse(self, source: SourceFile) -> SourceAST: ...
```

`SourceAST` exposes the query surface rules need (kept minimal, backend-agnostic):
`symbols() -> set[str]`, `imports() -> set[str]`, `calls(name) -> list[CallSite]`,
`string_literals() -> list[Literal]`, `type_references() -> set[str]` — each
`CallSite`/`Literal` carrying `file` + `line`.

`build_parser(backend: str = "auto") -> SourceParser` selects:

- **tree-sitter** (default) — `TreeSitterParser`, using `tree-sitter` +
  `tree-sitter-language-pack` (Swift + Obj-C grammars). Lazy-imported behind the
  `[code]` extra. If the extra is not installed, `available()` is `False` and the
  analyzer reports a factual "install `asc-metadata-verifier[code]`" message —
  it never silently returns zero findings as if the code were clean.
- **SwiftSyntax** (optional) — `SwiftSyntaxParser`, shelling out to a Swift
  toolchain, behind `[code-swift]`. If selected but no toolchain is present,
  `available()` is `False`; the analyzer records
  `parser_backend="swiftsyntax(unavailable)"` and **falls back to tree-sitter**.
  It never fabricates an AST. (Obj-C always routes through tree-sitter.)

`backend="auto"` uses tree-sitter. `backend="swiftsyntax"` requests the optional
backend with the documented fallback.

---

## Component 3 — Rule engine (`code/rules/` + `code/analyzer.py`)

`Rule` protocol:

```
class Rule(Protocol):
    id: str
    category: str
    guideline_ref: str
    severity: Literal["low", "medium", "high"]
    interpretive: bool          # True -> eligible for jury adjudication
    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]: ...
```

`REGISTRY: list[Rule]` collects every rule (one module per cluster:
`privacy.py`, `deprecated_api.py`, `security.py`, `compliance.py`).
`analyzer.analyze(project, parser) -> list[CodeFinding]` parses each source once
into an `ASTIndex` (keyed by path) and runs every rule. Pure/deterministic;
findings are sorted by `(file, line, rule_id)` for stable output.

### The curated catalog (v1)

Severity → gate level: **high → block-worthy**, medium/low → warn-worthy
(mirrors the judge's `_verdict_level` and the deterministic `_DETERMINISTIC_LEVEL`).

**Privacy & tracking — guideline 5.1.x:**

| rule_id | detects | guideline | sev | kind |
|---|---|---|---|---|
| `idfa-without-att` | IDFA symbols (`ASIdentifierManager`, `advertisingIdentifier`) used, but no `ATTrackingManager.requestTrackingAuthorization` call anywhere and/or `NSUserTrackingUsageDescription` missing from Info.plist | 5.1.2 | high | cross-artifact |
| `missing-usage-string` | a privacy-sensitive API family used in code (camera `AVCaptureDevice`, location `CLLocationManager`, contacts `CNContactStore`, photos `PHPhotoLibrary`, microphone, calendar `EKEventStore`, health `HKHealthStore`) with the matching `NS*UsageDescription` key absent from Info.plist | 5.1.1 | high | cross-artifact |
| `required-reason-api-undeclared` | a required-reason API called (`UserDefaults`, file-timestamp `.contentModificationDate`, `systemUptime`/`mach_absolute_time`, `stat`, disk-space, active-keyboard list) with `PrivacyInfo.xcprivacy` missing or lacking a matching `NSPrivacyAccessedAPIType` entry | Apple privacy-manifest policy | high | cross-artifact |
| `boilerplate-usage-string` | a `NS*UsageDescription` value that is empty, placeholder, or too generic to satisfy 5.1.1 | 5.1.1 | medium | config → **jury-escalated** (`interpretive=True`) |

**Deprecated / private API — guideline 2.5.x:**

| rule_id | detects | guideline | sev | kind |
|---|---|---|---|---|
| `uiwebview-usage` | any `UIWebView` reference/import (hard rejection since 2020) | 2.5.x | high | AST symbol |
| `private-api-symbol` | symbols on a curated denylist of well-known private APIs (`LSApplicationWorkspace`, `_UIBackdropView`, private setters) | 2.5.1 | high | AST symbol |

**Security / ATS — guideline 2.5.2:**

| rule_id | detects | guideline | sev | kind |
|---|---|---|---|---|
| `ats-arbitrary-loads` | `NSAppTransportSecurity → NSAllowsArbitraryLoads = true` in Info.plist (worse when paired with `http://` literals in source) | 2.5.2 | medium | config + AST |
| `insecure-http-endpoint` | hardcoded non-localhost `http://` URL literal in source | 2.5.2 | low | AST literal |

**Compliance & consistency:**

| rule_id | detects | guideline | sev | kind |
|---|---|---|---|---|
| `encryption-export-undeclared` | `ITSAppUsesNonExemptEncryption` absent from Info.plist (submission blocker) | export compliance | medium | config |
| `canopenurl-undeclared-scheme` | `canOpenURL`/`open` called with a scheme literal not present in `LSApplicationQueriesSchemes` | 2.5.x | low | cross-artifact |

Each rule module documents its **false-negative / false-positive** behavior in a
module docstring. The `private-api-symbol` and `required-reason-api-undeclared`
denylists live in dedicated data modules, explicitly marked non-exhaustive.

---

## Component 4 — Optional jury layer (`code/jury.py`)

Opt-in (`--jury`, same judges config + env-var API keys as the metadata jury).
**Off by default; offline default intact.** Two bounded modes, both grounded in
the live guidelines and reusing the panel's abstain/error isolation and consensus
policies:

1. **Adjudicate** findings from rules with `interpretive=True` (e.g.
   `boilerplate-usage-string`): the panel confirms, downgrades to WARN, or
   dismisses, writing a rationale + `guideline_ref`.
2. **Answer a fixed set of interpretive questions** over the relevant code
   regions — a closed list, not open-ended — e.g. account-gating vs **5.1.1(v)**,
   in-app-purchase-bypass signals vs **3.1.1**. Regions are selected by the static
   layer (which files reference the relevant symbols); the panel judges only those.

Every jury-produced item is a `CodeFinding` with `source="jury"` carrying the full
`PanelVerdict` (votes + consensus + agreement). The static catalog stands on its
own when the jury is off; the jury never runs unless explicitly enabled, and never
converts an LLM opinion into a `source="static"` fact.

---

## Component 5 — Data model (`models.py`, alongside `DeterministicFinding`)

```
CodeFinding:
  rule_id: str
  category: str
  severity: Literal["low", "medium", "high"]
  guideline_ref: str
  file: str
  line: int | None
  symbol: str | None
  evidence: str            # the offending quote / key path
  detail: str
  suggested_fix: str | None
  confidence: float        # 1.0 for static rules; panel confidence for jury items
  source: Literal["static", "jury"]
  panel: PanelVerdict | None   # set iff source == "jury"

CodeReport:
  status: Literal["PASS", "WARN", "BLOCK"]
  findings: list[CodeFinding]
  analyzed_files: int
  parser_backend: str
  jury_used: bool
```

`GateReport` gains `code_findings: list[CodeFinding] = []` so `verify --code`
returns one unified verdict. `evaluate(...)` gains a `_CODE_LEVEL` classifier
(high→block, medium/low→warn) mirroring `_DETERMINISTIC_LEVEL`, and folds
`code_findings` into the same rollup.

---

## Component 6 — CLI (`cli.py`)

New standalone command (registered on the existing `DefaultCommandGroup` app —
bare `asc-verify <path>` still resolves to `verify`):

```
asc-verify code <project-path>
    [--backend auto|swiftsyntax]
    [--jury] [--judges <judges.yaml>] [--policy <consensus-policy>]
    [--fail-on fail|warn]
    [--format text|json]
```

- Produces a `CodeReport`; text output groups findings by cluster with
  `file:line`, guideline ref, and evidence; `--format json` emits the full model.
- Exit code mirrors `verify` via the existing `report.exit_code`: **1 for BLOCK,
  0 otherwise** (WARN and PASS both exit 0). `--fail-on warn` promotes warn-level
  findings to BLOCK inside `evaluate` (so they then exit 1). Exit code **2** is
  reserved for input/usage errors (unreadable path, `[code]` extra missing),
  matching how `verify` already uses `typer.Exit(code=2)` for ingest errors.

`verify` gains one flag:

```
asc-verify verify <meta-source> --code <project-path> [existing flags...]
```

folding `CodeFinding`s into the unified `GateReport`. Without `--code`, `verify`
is unchanged.

---

## Testing strategy

- **Synthetic project fixtures** under `tests/fixtures/projects/` — small trees of
  `.swift`/`.m` files + `Info.plist` + `PrivacyInfo.xcprivacy`. Each rule gets a
  **hit fixture** (triggers the finding) and a **clean-pass fixture** (must not).
  Cross-artifact rules get fixtures that isolate each side (symbol present but
  manifest missing → hit; symbol present and manifest declared → pass).
- **tree-sitter** runs fully offline in CI (grammars vendored via the language
  pack). Tests requiring the `[code]` extra `importorskip("tree_sitter_language_pack")`.
- **Jury-layer** tests use the offline `FunctionModel`/`TestModel` like the
  existing jury suite — deterministic, no network, no keys.
- **SwiftSyntax backend** tests `skip` when no Swift toolchain is present; a
  dedicated test asserts the **unavailable → tree-sitter fallback** path with the
  factual `parser_backend` marker.
- **Gate integration** tests assert `_CODE_LEVEL` rollup and the unified
  `verify --code` verdict.
- **Determinism** test: analyzing the same fixture twice yields byte-identical
  ordered findings.
- **Backward-compat** guard: the full existing suite passes unchanged; plain
  `verify` and bare `asc-verify <path>` do zero extra I/O.

---

## Out of scope (kept honest & tight)

- Persisting `code` runs via the repository (B). `CodeReport` is a serializable
  pydantic model, so it slots into the existing `Repository` later — not wired
  this build.
- The D pages analyzer and E HTML report — separate specs.
- Full type inference, whole-program data-flow/taint, and dynamic analysis —
  explicitly beyond the AST-structural ceiling stated in the Global constraints.
  The tool must not claim these.
