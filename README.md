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

## The eval-science backbone

The judge is **measured, not asserted.** A curated golden dataset of **44 labeled cases** with **multi-label ground truth** (`src/asc_metadata_verifier/evals/golden/cases.jsonl` — 30 positives across all 8 rubric dimensions + 14 clean controls engineered to stress false positives) runs through a **pydantic-evals** meta-eval (`src/asc_metadata_verifier/evals/meta_eval.py`) that computes per-dimension precision/recall and overall accuracy over a full 44×8 one-vs-rest grid, plus a failure taxonomy (`false_negative` / `false_positive` / `wrong_dimension` / `wrong_severity`). Multi-label ground truth means a case that legitimately trips two dimensions (e.g. a keyword list that both stuffs keywords *and* names a competitor's trademark) isn't scored as a judge false positive. `BUILD_LOG.md` records the pre-registered methodology and the honest status of the real-model run (not yet executed — no key in the dev environment; no numbers fabricated).

## The bundled Claude skill

The package ships an `app-store-review-gate` skill (`src/asc_metadata_verifier/.agents/skills/app-store-review-gate/SKILL.md`) discovered via the [`library-skills`](https://github.com/tiangolo/library-skills) convention. It instructs Claude to run `asc-verify` on a given app, interpret the JSON gate report, present the decision with prioritized fixes, and **refuse to proceed to `ios-fastlane-ship` on a `BLOCK`** until the issues are resolved.

## Development

```bash
uv sync
uv run pytest          # 183 passed, 3 skipped (the skips are real-model tests, gated behind ANTHROPIC_API_KEY)
uv run ruff check .
```

The whole suite runs offline: model calls use pydantic-ai's `TestModel`/`FunctionModel`, the guidelines fetch and ASC API are mocked, and real-model tests are gated behind `ANTHROPIC_API_KEY`.

## License

Not yet chosen — see `LICENSE` (to be added). Until a license is added, all rights are reserved by default.
