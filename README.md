# asc-metadata-verifier

**An LLM-as-judge gate for App Store Connect metadata.** It ingests your app's metadata, judges it for **rejection risk** against the *live* App Store Review Guidelines using Claude, traces every judgment in **Logfire**, and returns a **PASS / WARN / BLOCK** decision — with quoted findings, guideline references, and concrete fixes — *before* you submit.

Built on the Pydantic tooling stack: **pydantic-ai** (the judge) · **pydantic-evals** (measuring the judge against a labeled golden set) · **Logfire** (observability) · **typer** (CLI) · **library-skills** (skill bundling).

> **Status — Phase 1 + Phase 2 shipped.** fastlane + YAML ingest, deterministic checks, a live-guidelines-grounded LLM judge, the gate/report, the `asc-verify` CLI, a 44-case golden meta-eval, a bundled Claude skill (Phase 1), plus a live App Store Connect API ingest adapter and a vision pass over screenshots (Phase 2) are all built and tested (`BUILD_LOG.md` is the honest build record).
>
> **Honestly unvalidated:** the ASC-API adapter is tested only against **mocked `httpx`** (no live App Store Connect credentials were used), and the vision judge is tested only against a **`FunctionModel` stub** (no real-model vision run). Per the honesty bar, no accuracy numbers are claimed that weren't measured.

## Why

App Store metadata rejections cost days: you submit, wait for review, get rejected for something a checklist could have caught (an Android mention in the description, a price in the wrong field, placeholder text that shipped by accident), fix it, and re-queue. This gates that class of problem *before* submission — and does it where a regex can't: judging phrasing, claims, and screenshots against the *current* guidelines.

## How it works

```
                 fastlane ─┐
                 YAML      ├─▶  AppMetadata  ─▶  deterministic checks  ─▶  LLM-as-judge  ─▶  gate  ─▶  PASS / WARN / BLOCK
  App Store Connect API ──┘   (canonical model)   (char limits, empty      (Claude, per       (aggregate)   + report (md/json)
                                                    required fields,         rubric dimension,               + exit code (0/1)
                                                    placeholder/URL          grounded in the
                                                    regexes — LLM-free)      LIVE guidelines)
                                                                                   │
                                              vision judge over screenshots ───────┤
                                                                                   ▼
                                              every step traced in Logfire ──────────────
```

- **Deterministic first** — anything a character count or regex settles (over-limit fields, missing required fields, `lorem`/`TODO`/placeholder text, malformed URLs) never spends an LLM call.
- **The judge is grounded in the live guidelines** — the current [App Store Review Guidelines](https://developer.apple.com/app-store/review/guidelines/) are fetched at review time, cached for the session only (never committed — no stale snapshot), and passed to the judge as grounding. Every `guideline_ref` cites text the judge actually saw; if the fetch fails, it runs without citations and says so — it never invents a reference.
- **The gate** blocks on hard rejections (`over_limit` / `missing_required`, or any high-severity judge `fail`) and warns on softer signals — configurable with `--fail-on`.

## What it checks

**Rubric (rejection-risk, 8 text dimensions):** placeholder/incomplete text · other-platform mentions (Android / Google Play) · misleading claims · price/terms in the description · keyword stuffing / competitor names · beta/demo mentions · unauthorized contact info & links · third-party trademarks.

**Vision (4 screenshot dimensions):** placeholder/mockup art · other-platform UI chrome · misleading depictions · excessive marketing text. Gated the same way as the text judge (see `--no-vision`).

**Deterministic (LLM-free):** per-field character limits, required fields, placeholder patterns, malformed URLs.

## Install

```bash
uv add asc-metadata-verifier
uvx library-skills --claude   # discovers + installs the bundled `app-store-review-gate` skill into ~/.claude/skills
```

Plain `uvx library-skills` (no flag) targets the generic `.agents/skills` directory, which Claude Code doesn't read — Claude Code users need `--claude` (or select `.claude/skills` when prompted).

**Manual fallback** (no `library-skills` available) — copy the **whole skill directory**, not just `SKILL.md`:

```bash
cp -r site-packages/asc_metadata_verifier/.agents/skills/app-store-review-gate ~/.claude/skills/
```

## Usage

```bash
asc-verify ./fastlane                 # fastlane `deliver` root (the parent of metadata/ and screenshots/)
asc-verify --yaml metadata.yaml       # a single YAML/JSON file instead of fastlane
asc-verify ./fastlane --format json   # raw JSON on stdout, pipeable/parseable
asc-verify ./fastlane --dry-run       # deterministic checks + gate only — fully offline, no key
```

| Flag | Meaning |
|---|---|
| `--yaml <file>` | Use the YAML adapter on this file instead of a fastlane path. |
| `--asc-api-app-id <id>` | App Store Connect app id. Requires the other three `--asc-api-*` flags; when all four are given, fetches metadata live from the App Store Connect API. |
| `--asc-api-key-id <id>` | ASC API key id (from the `.p8` key). |
| `--asc-api-issuer-id <id>` | ASC API issuer id. |
| `--asc-api-key <path>` | Path to the ASC API private key (`.p8` file — never committed; `.gitignore` blocks `*.p8`). |
| `--format {md,json}` | Report format (default `md`). `json` is raw stdout. |
| `--fail-on {warn,fail}` | Gate threshold: block on any `fail` (default) or already on `warn`. |
| `--guidelines <path>` | Local offline copy of the guidelines; skips the live fetch. |
| `--dry-run` | Deterministic checks + gate only — no guidelines fetch, no judge, fully offline. |
| `--no-vision` | Skip the vision screenshot judge. |

The **text judge** runs only when `ANTHROPIC_API_KEY` is set (or a model is injected programmatically) and `--dry-run` is not passed; otherwise the CLI still runs deterministic checks + the gate and prints `LLM checks skipped (no ANTHROPIC_API_KEY)`. The **vision judge** additionally requires `--no-vision` to be unset and at least one screenshot present; its verdicts merge into the same gate.

Exit code is `1` on `BLOCK`, `0` otherwise — so it gates a fastlane pipeline. Run `logfire auth` to see the full source→gate trace.

### Example

`tests/fixtures/fastlane_flawed/` is a deliver root with four planted issues (over-limit app name, placeholder text, an Android mention, a price in the description). `tests/test_e2e.py` drives the real CLI against it end-to-end, offline (a stubbed judge stands in for the real LLM call, so no network/key is needed), producing this actual report — reproduced verbatim (the `guideline` fields read `n/a` *because this run has no live guidelines text*; per the honesty bar, `guideline_ref` is only ever populated from grounding the judge actually saw, never invented):

```
# ASC Metadata Verifier Report: BLOCK

_Note: guideline references unavailable (offline)._

## Rubric verdicts

### en-US / other_platform_mentions

- **field:** promotional_text — **verdict:** fail (severity: high)
  - **offending quote:** Also available on Android and Google Play!
  - **guideline:** n/a
  - **rationale:** Promotional text references Android and Google Play.
  - **suggested fix:** Remove references to Android/Google Play

### en-US / price_terms_in_description

- **field:** description — **verdict:** fail (severity: high)
  - **offending quote:** only $2.99 this week
  - **guideline:** n/a
  - **rationale:** Description embeds a discounted price for Premium.
  - **suggested fix:** Move pricing out of the description

## Deterministic findings

- **en-US / app_name** (over_limit): exceeds 30-char limit by 7 (len 37)
- **en-US / description** (placeholder): contains placeholder-like text: 'Lorem', 'ipsum', 'TODO'
```

Exit code `1` (BLOCK). With a real `ANTHROPIC_API_KEY`, network access, and no `--guidelines` override, the judge calls the real model against the live guidelines instead — the verdict/rationale wording will differ from this stub, and `guideline` is populated with an actual cited section rather than `n/a`.

## Multi-LLM jury (optional)

By default `asc-verify` judges with a single Claude model — that's everything documented above, and it is unchanged. Pass `--judges` and/or `--judge` to instead judge every rubric dimension with a **panel of independent LLM judges** (any mix of Anthropic and OpenAI-compatible models) and combine their votes into one consensus verdict per (locale, dimension) unit:

```bash
asc-verify ./fastlane --judges judges.yaml                                      # jury from a config file
asc-verify ./fastlane --judge anthropic:claude-sonnet-5 --judge openai:gpt-4o   # jury from inline specs, no file
asc-verify ./fastlane --judges judges.yaml --consensus unanimous --max-concurrency 4
```

**`judges.yaml` schema.** Secrets are referenced by **environment variable name only** — a config file never contains a raw API key. `judges.example.yaml` (repo root):

```yaml
# Example jury configuration for `asc-verify --judges judges.yaml`.
# Secrets are referenced by ENV VAR NAME only — never put a raw key here.
# Default consensus when omitted: majority_severe. Override per run with --consensus.
consensus: majority_severe
judges:
  - name: claude
    provider: anthropic
    model: claude-sonnet-5
    api_key_env: ANTHROPIC_API_KEY
    vision: true
  - name: gpt4o
    provider: openai            # provider "openai" = OpenAI OR any OpenAI-compatible endpoint
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
    vision: true
  - name: local-llama           # self-hosted via an OpenAI-compatible server (Ollama/vLLM/LM Studio)
    provider: openai
    model: llama3.1:70b
    base_url: http://localhost:11434/v1
    vision: false
```

| Field | Meaning |
|---|---|
| `name` | Judge identifier — used for `--judge` merge-by-name and in reports. |
| `provider` | `anthropic` or `openai`. `openai` also covers any OpenAI-compatible endpoint (see self-hosted note below). |
| `model` | Model name/id passed to the provider. |
| `api_key_env` | Name of the environment variable holding the API key (defaults to `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` per provider if omitted). Never a literal key. |
| `base_url` | Optional — overrides the provider's default endpoint, for self-hosted models. |
| `vision` | Whether this judge also votes on screenshots. |

A judge with no resolvable API key and no `base_url` is **unavailable** and is silently omitted when the panel is built; if every configured judge is unavailable, the run degrades to the same deterministic-only path as running with no `--judges` and no key set at all.

**`--judge`** adds or overrides one judge inline, no file needed: `[name=]provider:model[@base_url]`, repeatable, merged with `--judges` by name (a CLI `--judge` of the same name overrides a file entry; unmatched CLI specs are appended).

**`--max-concurrency`** (default `8`) caps how many judge calls are in flight at once across the whole panel run.

**Consensus policies** (`--consensus`, applied per unit over that unit's non-abstaining votes):

| Policy | Rule |
|---|---|
| `majority_severe` (default) | The verdict with the most votes wins; ties are broken toward the more severe verdict. |
| `most_severe` | The single most severe vote among all judges wins, regardless of how many judges agree. |
| `unanimous` | The least severe vote among all judges wins — a verdict escalates to `warn`/`fail` only when every voting judge agrees at least that severe; a single dissenting `pass` pulls the result back to `pass`. |
| `confidence_weighted` | Each judge's confidence score is summed per verdict; the verdict with the highest total confidence wins (ties broken toward the more severe). |

**Self-hosted judges.** `provider: openai` means "any OpenAI-compatible chat-completions endpoint," not only OpenAI's hosted API — point `base_url` at a local Ollama, vLLM, or LM Studio server (see `local-llama` above) to run a judge with no external API call at all.

Panel output — every judge's vote plus the consensus — appears in both report formats: a "Panel deliberation" section in the markdown report, and the `panels` array in `--format json`.

> **Honest status:** the default (no `--judges`) is unchanged single-Claude v1. The aggregation logic is validated offline with synthetic judges (`tests/test_jury_eval.py`). A live 3-judge Claude panel (haiku-4.5 + sonnet-5 + opus-4.8) has now been run over the full 44-case golden set — all 1,056 grid cells voted (0 errored). Headline: best single judge **95.5% (42/44)**; the `unanimous` policy reaches **100% (44/44)** — a genuine but modest **+2-case** lift — while `most_severe` is worse (−7 cases) and `majority`/`confidence_weighted` tie. Inter-judge Fleiss κ is high on objective categories (trademark 0.91, price 0.84) and low on subjective ones (placeholder 0.22). Small N; grounding-free; `confidence_weighted` is degenerate on the offline-scored path. Full breakdown + caveats in [`BUILD_LOG.md`](BUILD_LOG.md).

## Persistence (optional)

By default `asc-verify` prints a report and exits — nothing is written to disk. Pass `--db` to opt into a small persistence layer: saved run history, an optional judge-verdict cache, and cross-run diffing.

```bash
asc-verify ./fastlane --db sqlite:///runs.db          # verify and save this run
asc-verify ./fastlane --db runs.db                    # a bare path works too, no scheme needed
asc-verify ./fastlane --db runs.db --cache            # also reuse/store single-judge verdicts
asc-verify ./fastlane --db runs.db --no-save          # cache reads/writes still happen, this run just isn't saved

asc-verify history --db runs.db                                    # list saved runs, newest first
asc-verify history --db runs.db --app-id 123456789 --format json
asc-verify diff <run-id-a> <run-id-b> --db runs.db                 # new / resolved / persisting / severity-changed findings
asc-verify similar "some finding text" -k 5                        # semantic recall — see below, requires setup
```

| Flag | Meaning |
|---|---|
| `--db <url-or-path>` | Enables persistence. Accepts a URL (`sqlite:///runs.db`) or a bare filesystem path (`runs.db`) — a bare path is dispatched to the sqlite backend directly. Omit it and nothing changes: `asc-verify` behaves exactly as documented earlier in this README. |
| `--cache` / `--no-cache` | Reuse/store single-judge text verdicts in `--db`, keyed by prompt + model (see below). Default off; no effect without `--db`. Not applied to the multi-LLM jury path (`--judges`/`--judge`) — jury-path caching is out of scope for this version. |
| `--no-save` | Skip saving this run's report to `--db` (a `--cache` read/write, if enabled, still happens). |

`history [--app-id] [--limit] [--format {md,json}]` and `diff <run-a> <run-b> [--format {md,json}]` both require `--db` and read from it; `history` lists saved runs (newest first, optionally filtered to one `app_id`), `diff` compares two saved runs' findings. `asc-verify <path>` with no subcommand still works exactly as before — `verify` is the default command whenever the first token isn't a recognized subcommand name.

**Repository pattern.** Persistence goes through a `Repository` protocol (`persistence/repository.py`) — `save_run` / `get_run` / `list_runs` plus the verdict-cache and guideline-snapshot methods. The only backend this codebase ships is `SqliteRepository`, built on the Python standard library's `sqlite3` (no ORM, no new runtime dependency). `--db` values are dispatched by URL scheme through a small registry (`persistence/config.py`'s `BACKENDS` dict, currently `{"sqlite": ...}`), so a future backend can register itself by scheme without touching the CLI.

**Verdict cache.** `--cache` keys each single-judge text verdict on a hash of the resolved model name, the full built prompt (which already encodes the rubric dimension, the locale text, and the grounding actually used), and `PROMPT_VERSION` — a hash of the judge's system prompt. A cache **hit is only ever the identical prior computation**: changing the model, the prompt content, or the system prompt itself changes the key and forces a fresh judge call. It never rewrites, reinterprets, or otherwise alters a verdict.

**Semantic recall (`similar`) — opt-in, bring-your-own embedder.** `asc-verify similar "<text>"` is meant to look up past findings by meaning rather than exact text, via a `SemanticIndex` protocol (`persistence/semantic.py`). This codebase ships:
- `Embedder` / `SemanticIndex` protocols,
- `StubEmbedder` + `InMemoryIndex` — a deterministic, offline, dependency-free bag-of-tokens embedder and index used for tests and local dev; it has no notion of meaning and is not a real embedding model,
- `ChromaIndex` — a `SemanticIndex` backed by `chromadb`, gated behind the optional `semantic` extra (`uv add "asc-metadata-verifier[semantic]"`) and imported lazily inside `ChromaIndex.__init__`, so installing the base package never pulls in `chromadb`.

There is **no bundled/default embedding model.** `ChromaIndex` always takes an injected `Embedder`; this codebase provides no real one, and wiring a real embedder (and assigning it to the CLI's semantic-index seam) is left entirely to the caller. With nothing configured, `similar` exits with an actionable error instead of a traceback.

> **Honest status.** With no `--db`, `asc-verify` is unchanged from every example earlier in this README: byte-identical output, fully offline, zero new dependencies. The verdict cache never alters a verdict — a hit is always a literal replay of an earlier, identical computation. `ChromaIndex` plus a real embedder has **not** been exercised in CI: `chromadb` is an optional extra CI does not install, and its one test (`tests/test_semantic.py::test_chroma_index_gated_behind_dependency`) uses `pytest.importorskip("chromadb")` and skips cleanly rather than running — only `StubEmbedder`/`InMemoryIndex` are genuinely exercised. Semantic recall has no default wiring in this codebase at all: using it for real requires the caller to supply both an embedder and an index.

## Code analysis (optional)

Beyond metadata, `asc-verify` can scan the app's **source and config** for rejection risk — a deep, AST-level static analysis of a local Apple project (Swift/Obj-C + `Info.plist` + `*.entitlements` + `PrivacyInfo.xcprivacy`). Install the extra and point it at the project root:

```bash
uv sync --extra code            # or: pip install "asc-metadata-verifier[code]"
asc-verify code path/to/MyApp                 # standalone; exits 1 on BLOCK
asc-verify code path/to/MyApp --format json   # full CodeReport as JSON
asc-verify verify <metadata> --code path/to/MyApp   # fold code findings into one gate
```

Every finding is anchored to a real `file:line` + an `evidence` quote and maps to a specific App Store Review Guideline. The curated rule catalog:

| rule_id | guideline | severity |
|---|---|---|
| `idfa-without-att` (IDFA used, no ATT prompt / usage string) | 5.1.2 | high |
| `missing-usage-string` (privacy API used, `NS*UsageDescription` absent) | 5.1.1 | high |
| `required-reason-api-undeclared` (required-reason API vs `PrivacyInfo.xcprivacy`) | privacy-manifest | high |
| `boilerplate-usage-string` (vague usage string) | 5.1.1 | medium |
| `uiwebview-usage` | 2.5.x | high |
| `private-api-symbol` (curated denylist) | 2.5.1 | high |
| `ats-arbitrary-loads` (`NSAllowsArbitraryLoads`) | 2.5.2 | medium |
| `insecure-http-endpoint` (`http://` literal) | 2.5.2 | low |
| `encryption-export-undeclared` (`ITSAppUsesNonExemptEncryption` absent) | export compliance | medium |
| `canopenurl-undeclared-scheme` (scheme not in `LSApplicationQueriesSchemes`) | 2.5.x | low |

The parser is pluggable: **tree-sitter** is the default offline backend (Swift + Obj-C grammars, no Xcode needed). An optional higher-fidelity **SwiftSyntax** backend is a **bring-your-own subprocess helper** — `--backend swiftsyntax --swiftsyntax-cmd <cmd>` (or `ASC_SWIFTSYNTAX_CMD`); a command that reads a source path and prints AST-surface JSON. If it's unavailable, the analyzer falls back to tree-sitter with a factual `swiftsyntax(unavailable)` marker rather than fabricating anything.

An **opt-in LLM jury** (`--jury --judges judges.yaml`) judges the interpretive calls the AST can't decide — vague usage strings, and a fixed set of questions like account-gating vs 5.1.1(v) or IAP-bypass vs 3.1.1. Jury-produced items are tagged `source: "jury"` and carry the full vote record; they are never presented as deterministic facts.

> **Honest status & boundary.** This is **AST-structural** analysis — symbol/import/call/string presence with token-accurate boundaries and cross-artifact (code × manifest) correlation. It is **not** full type inference, whole-program data-flow/taint, or dynamic analysis, and it never claims to be. The rule catalog and the `private-api-symbol` / `required-reason-api-undeclared` lists are **curated and non-exhaustive** — false negatives are expected and documented per rule module. With no `code` command and no `--code` flag, `verify` is byte-unchanged and pulls zero new core dependencies (tree-sitter lives behind the `[code]` extra). `code` with no `--jury` makes zero network calls. The SwiftSyntax backend is exercised in tests only via a fake helper (no real Swift toolchain in CI); the fallback path is directly tested.

## Pages analysis (optional)

Beyond metadata and code, `asc-verify` can check the app's **external web pages** — the declared privacy-policy, support, and marketing URLs — for rejection risk:

```bash
asc-verify pages <metadata-source>                    # fetch + reachability, exits 1 on BLOCK
asc-verify pages --yaml metadata.yaml --pages-dir ./snapshots   # fully offline (saved HTML)
asc-verify pages --yaml metadata.yaml --code ./MyApp --jury --judges judges.yaml
asc-verify verify ./fastlane --pages                  # fold page reachability into the unified gate
```

- **Deterministic reachability** (offline-capable, no LLM): `page-unreachable` (a declared URL that 404s/times out — a near-certain **5.1.1** rejection for privacy/support), `page-empty`, `page-offsite-redirect`, and `privacy-policy-missing`.
- **Opt-in jury** (`--jury`): judges privacy-policy adequacy (5.1.1), support-page adequacy, and marketing overclaim (2.3.x). With `--code`, it runs the **privacy↔code cross-reference** — `build_profile` maps the code analyzer's findings to policy-relevant data categories (camera, location, contacts, photos, mic, calendar, health, advertising identifier) and the jury judges whether the fetched policy actually discloses each. Undisclosed collection → a `privacy-code-mismatch` finding, tagged `source: "jury"` with the full vote record.

The fetcher is **bounded and SSRF-guarded**: http(s) only, a resolved host in a private/loopback/link-local/reserved range is refused, each redirect hop is re-validated (hop-capped), with a connect/read timeout and a streamed response-size cap.

> **Honest status & boundary.** `pages` **does** use the network by design (it fetches live pages) — `--pages-dir` (a `pages.json` manifest of saved HTML) gives a fully offline path, and the whole test suite runs offline via a local fetcher / mocked transport. **Zero new core deps** (httpx is already present). The SSRF guard is **resolve-then-check**, so **DNS-rebinding is a known residual** not hardened in this build. The cross-reference is **jury-judged** (soft, LLM opinion, never asserted as deterministic fact) and needs `--jury` + `--code`; without them, `pages` is reachability-only. It does **not** crawl or follow links, and `pages` runs are not yet persisted.

## The eval-science backbone

The judge is **measured, not asserted.** A curated golden dataset of **44 labeled cases** with **multi-label ground truth** (`src/asc_metadata_verifier/evals/golden/cases.jsonl` — 30 positives across all 8 rubric dimensions + 14 clean controls engineered to stress false positives) runs through a **pydantic-evals** meta-eval (`src/asc_metadata_verifier/evals/meta_eval.py`) that computes per-dimension precision/recall and overall accuracy over a full 44×8 one-vs-rest grid, plus a failure taxonomy (`false_negative` / `false_positive` / `wrong_dimension` / `wrong_severity`). Multi-label ground truth means a case that legitimately trips two dimensions (e.g. a keyword list that both stuffs keywords *and* names a competitor's trademark) isn't scored as a judge false positive. `BUILD_LOG.md` records the pre-registered methodology and the honest status of the real-model run (not yet executed — no key in the dev environment; no numbers fabricated).

## The bundled Claude skill

The package ships an `app-store-review-gate` skill (`src/asc_metadata_verifier/.agents/skills/app-store-review-gate/SKILL.md`) discovered via the [`library-skills`](https://github.com/tiangolo/library-skills) convention. It instructs Claude to run `asc-verify` on a given app, interpret the JSON gate report, present the decision with prioritized fixes, and **refuse to proceed to `ios-fastlane-ship` on a `BLOCK`** until the issues are resolved.

## Development

```bash
uv sync --extra code   # `--extra code` adds the tree-sitter grammars the code analyzer needs
uv run pytest          # 370 passed, 4 skipped with the [code] extra installed. The 4 skips: 3 real-model
                        # tests gated behind ANTHROPIC_API_KEY, 1 ChromaIndex test gated behind the
                        # `semantic` extra. Without `--extra code`, the tree-sitter-backed code tests
                        # (parser + code CLI) additionally skip via pytest.importorskip.
uv run ruff check .
```

The whole suite runs offline: model calls use pydantic-ai's `TestModel`/`FunctionModel`, the guidelines fetch and ASC API are mocked, the code analyzer's tree-sitter grammars are vendored by the `[code]` extra, and real-model tests are gated behind `ANTHROPIC_API_KEY`.

## License

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 Vitalii Komarovskyi.
