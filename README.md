# asc-metadata-verifier

**LLM-as-judge gate for App Store Connect metadata.** Ingests your app's metadata (fastlane · YAML), judges it for **rejection risk** against the *live* App Store Review Guidelines using Claude, traces every judgment in **Logfire**, and returns a **PASS / WARN / BLOCK** decision with quoted findings, guideline references, and fixes — *before* you ship.

Built on the Pydantic tooling stack: **pydantic-ai** (the judge) · **pydantic-evals** (validating the judge against a labeled golden set) · **Logfire** (observability) · **typer** (CLI) · **library-skills** (skill bundling).

> **Status: Phase 1 + Phase 2 shipped.** fastlane + YAML ingest, deterministic checks, a live-guidelines-grounded LLM judge, the gate/report, the `asc-verify` CLI, a 44-case golden meta-eval, and a bundled Claude skill (Phase 1) — plus a live App Store Connect API ingest adapter and a vision pass over screenshots (Phase 2) — are all built and tested (see `BUILD_LOG.md` for the honest build record). **Honestly unvalidated:** the ASC-API adapter is tested only against mocked `httpx` responses (no live App Store Connect credentials in this dev environment), and the vision judge is tested only against a `FunctionModel` stub (no real-model vision run). See [`docs/superpowers/specs/2026-08-08-asc-metadata-verifier-design.md`](docs/superpowers/specs/2026-08-08-asc-metadata-verifier-design.md) for the full design.

## What it checks (MVP rubric: rejection risk)
Placeholder/incomplete text · other-platform mentions (Android/Google Play) · misleading claims · price/terms in the description · keyword stuffing / competitor names · beta/demo mentions · unauthorized contact info & links · third-party trademarks — plus deterministic character-limit and required-field checks. A vision pass over screenshots (placeholder/mockup art, Android UI chrome, misleading depictions, excessive marketing text) also runs against the four screenshot dimensions, gated the same way as the text judge (see `--no-vision` below).

## Install

Install the library, then let `library-skills` install the bundled Claude skill:

```bash
uv add asc-metadata-verifier
uvx library-skills --claude  # discovers + installs the bundled `app-store-review-gate` skill into ~/.claude/skills
```

Plain `uvx library-skills` (no flag) targets the generic `.agents/skills` directory, which Claude Code doesn't read — Claude Code users need the `--claude` flag (or to select `.claude/skills` when prompted interactively).

**Manual fallback** (no `library-skills` tool available): copy the **whole skill directory** — not just `SKILL.md` — into `~/.claude/skills/`:

```bash
cp -r site-packages/asc_metadata_verifier/.agents/skills/app-store-review-gate ~/.claude/skills/
```

## Usage

```bash
asc-verify ./fastlane                 # fastlane `deliver` root (parent of metadata/, screenshots/)
asc-verify --yaml metadata.yaml       # single YAML/JSON file instead of fastlane
```

Options:

| Flag | Meaning |
|---|---|
| `--yaml <file>` | Use the YAML adapter on this file instead of a fastlane path. |
| `--asc-api-app-id <id>` | App Store Connect app id. Requires the other three `--asc-api-*` flags too; when all four are given, fetches metadata live from the App Store Connect API instead of fastlane/`--yaml`. |
| `--asc-api-key-id <id>` | App Store Connect API key id (from the `.p8` key). |
| `--asc-api-issuer-id <id>` | App Store Connect API issuer id. |
| `--asc-api-key <path>` | Path to the App Store Connect API private key (`.p8` file). |
| `--format {md,json}` | Report format (default `md`). `json` is raw stdout, pipeable/parseable. |
| `--fail-on {warn,fail}` | Gate threshold: block on any `fail` (default) or already on `warn`. |
| `--guidelines <path>` | Local offline copy of the App Store Review Guidelines; skips the live fetch. |
| `--dry-run` | Deterministic checks + gate only — no guidelines fetch, no judge, fully offline. |
| `--no-vision` | Skip the vision screenshot judge. Without this flag, the vision judge runs whenever an API key/model is available and there are screenshots to judge. |

The judge itself only runs when `ANTHROPIC_API_KEY` is set (or a model is injected programmatically) and `--dry-run` is not passed; otherwise the CLI still runs deterministic checks + gate and prints `LLM checks skipped (no ANTHROPIC_API_KEY)`. The vision judge additionally requires `--no-vision` to be unset and at least one screenshot in the ingested metadata; its verdicts merge into the same gate as the text judge's.

Exit code is `1` on `BLOCK`, `0` otherwise — so it gates a fastlane pipeline. Configure Logfire (`logfire auth`) to see the full source→gate trace.

**Example** — `tests/fixtures/fastlane_flawed/` is a fastlane deliver root with four planted issues (over-limit app name, placeholder text, an Android mention, and a price embedded in the description). `tests/test_e2e.py` drives the real CLI against it end-to-end, offline (a stubbed judge stands in for the real LLM call, so no network/API key is needed), and produces this actual report — reproduced verbatim below (the `guideline` fields show `n/a` here specifically because this run has no live guidelines text; per the honesty bar, `guideline_ref` is only ever populated from grounding text the judge actually saw, never invented):

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

Exit code `1` (BLOCK). Run with a real `ANTHROPIC_API_KEY`, network access, and no guideline override, and the judge instead calls the real model against the live App Store Review Guidelines — the verdict/rationale wording will differ from this stub, and `guideline` gets populated with an actual cited section instead of `n/a`.

Not built yet, and deliberately not documented as a CLI flag: `--rubric` (there is currently one rubric). The `--asc-api-*` flags (live App Store Connect API ingest) and the vision screenshot judge shipped in Phase 2 — see `BUILD_LOG.md` for the honest status of what's validated against real ASC credentials/a real model versus mocked/stubbed tests only.

## The eval-science backbone
The judge is **measured, not asserted**: a curated golden dataset of **44 labeled cases** with **multi-label ground truth** (`src/asc_metadata_verifier/evals/golden/cases.jsonl` — 30 positives across all 8 rubric dimensions + 14 clean controls engineered to stress false positives) is run through a **pydantic-evals** meta-eval (`src/asc_metadata_verifier/evals/meta_eval.py`) that computes per-dimension precision/recall and overall accuracy against a full 44×8 one-vs-rest grid, plus a failure taxonomy (`false_negative` / `false_positive` / `wrong_dimension` / `wrong_severity`). Every judge call is traced in Logfire. See `BUILD_LOG.md` for the pre-registered methodology and the honest status of the real-model run.

## License
TBD.
