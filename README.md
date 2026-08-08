# asc-metadata-verifier

**LLM-as-judge gate for App Store Connect metadata.** Ingests your app's metadata (fastlane · YAML · App Store Connect API), judges it for **rejection risk** against the App Store Review Guidelines using Claude, traces every judgment in **Logfire**, and returns a **PASS / WARN / BLOCK** decision with quoted findings, guideline references, and fixes — *before* you ship.

Built on the Pydantic tooling stack: **pydantic-ai** (the judge) · **pydantic-evals** (validating the judge against a labeled golden set) · **Logfire** (observability) · **typer** (CLI) · **library-skills** (skill bundling).

> Status: pre-registration / design phase. See [`docs/superpowers/specs/2026-08-08-asc-metadata-verifier-design.md`](docs/superpowers/specs/2026-08-08-asc-metadata-verifier-design.md) for the full design.

## What it checks (MVP rubric: rejection risk)
Placeholder/incomplete text · other-platform mentions (Android/Google Play) · misleading claims · price/terms in the description · keyword stuffing / competitor names · beta/demo mentions · unauthorized contact info & links · third-party trademarks — plus deterministic character-limit and required-field checks, and (Phase 2) a vision pass over screenshots.

## Install

Install the library, then let `library-skills` install the bundled Claude skill:

```bash
uv add asc-metadata-verifier
uvx library-skills          # discovers + installs the bundled `app-store-review-gate` skill
```

(Manual fallback: copy `app-store-review-gate/SKILL.md` into `~/.claude/skills/app-store-review-gate/`.)

## Usage

```bash
asc-verify ./fastlane/metadata            # fastlane deliver folder
asc-verify --yaml metadata.yaml           # single YAML/JSON file
asc-verify --asc-api --app-id … --key-id … --issuer-id … --key AuthKey.p8   # live fetch
asc-verify ./fastlane/metadata --format json --fail-on fail                 # CI/fastlane gate
```

Exit code is non-zero on BLOCK, so it gates a fastlane pipeline. Configure Logfire (`logfire auth`) to see the full source→gate trace.

## The eval-science backbone
The judge is **measured, not asserted**: a curated golden dataset of known-rejectable + known-clean metadata (`src/asc_metadata_verifier/evals/golden/`) is run through **pydantic-evals** to report judge-vs-ground-truth agreement (precision/recall/accuracy) per rubric dimension, with a failure taxonomy.

## License
TBD.
