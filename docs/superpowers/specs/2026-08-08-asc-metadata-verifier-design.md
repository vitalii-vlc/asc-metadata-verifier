# ASC Metadata Verifier — Design Spec

> Pre-registration root commit — scope + design fixed **before** any feature code (honest-velocity method, mirroring the MCP Oversight Gateway). Date: 2026-08-08.

**Goal:** an LLM-as-judge tool that ingests an app's App Store Connect metadata, judges it for **rejection risk** against the App Store Review Guidelines, traces every judgment in **Logfire**, and returns a **PASS / WARN / BLOCK** gate with quoted findings, guideline references, and fixes — to run *before* shipping via `ios-fastlane-ship`.

**Architecture (one line):** deterministic pre-checks where a regex suffices, an LLM-as-judge (Claude via pydantic-ai) where judgment is needed, a curated golden dataset + pydantic-evals to measure the judge itself, all observable in Logfire, packaged as a pip-installable library that bundles a Claude skill (installable/discoverable via `library-skills`).

**Tech stack:** Python (uv) · pydantic-ai (Claude judge, structured output) · pydantic-evals (judge validation) · logfire (tracing) · pydantic (models) · httpx + PyJWT + cryptography (ASC API) · pyyaml · typer + rich (CLI) · library-skills convention (skill bundling).

---

## Global constraints
- **Honesty bar (hard):** no fabricated findings, no invented `library-skills` convention. Every `guideline_ref` must cite the **current App Store Review Guidelines fetched live at review time** — never a hardcoded/bundled snapshot, never an invented reference. Where a mechanism is unknown, derive it from the authoritative source before coding it.
- **Determinism first:** never spend an LLM call on what a character-count or regex settles objectively.
- **Judge must be measurable:** every rubric dimension is validated against a labeled golden set (agreement statistics), not asserted.
- **Offline-safe:** deterministic checks and the full CLI shape work with no API key (LLM/vision degrade gracefully, clearly flagged).
- **Judge model:** Claude Sonnet 5 default, configurable.

## Non-goals (MVP)
- ASO quality scoring and localization-consistency scoring (architecture keeps them pluggable as future rubrics; not built now).
- Auto-fixing / rewriting metadata (we flag + suggest; we do not mutate the user's metadata).
- Publishing to PyPI (structured for it; actual publish is a later, user-triggered step).

---

## Data flow
```
source ─┐
fastlane │
YAML     ├─▶ Ingest adapter ─▶ AppMetadata ─▶ deterministic ─▶ LLM-as-judge ─▶ aggregate ─▶ GATE
ASC API ─┘   (normalize)      (canonical)     pre-checks        (Claude, one     Gate      PASS / WARN / BLOCK
                                              (char limits,      call per rubric  verdicts  + report.md / report.json
                                               empties,          dimension +                + exit code (CI/fastlane gate)
                                               placeholder        vision for
                                               regexes)           screenshots)
        └────────────────────────── every span traced in Logfire ──────────────────────────┘
```

## Components (module map)
- `models.py` — `AppMetadata`, `LocaleMetadata`, `Screenshot`, `RubricVerdict{dimension, verdict(pass|warn|fail), severity, confidence, rationale, offending_quote, guideline_ref, suggested_fix}`, `GateReport` (all pydantic).
- `limits.py` — per-field character limits + required fields (name 30, subtitle 30, keywords 100, promo 170, description 4000, …).
- `ingest/` — `base.py` (adapter protocol → `AppMetadata`), `fastlane.py` (`metadata/<locale>/*.txt` + screenshots dir), `yaml_source.py` (single YAML/JSON), `asc_api.py` (JWT auth via issuer-id + key-id + `.p8`; live fetch of app info, version localizations, screenshots). **All three sources supported** (per decision).
- `checks/deterministic.py` — char limits, empty required fields, obvious placeholder/`lorem`/`TODO`/`XXX` patterns, malformed URLs. Cheap, objective, LLM-free.
- `guidelines/source.py` — fetches the **current App Store Review Guidelines** from the canonical URL at review time, session-caches them, and extracts the metadata-relevant sections as grounding context for the judge. Never bundled/committed. (See "Guidelines grounding" below.)
- `judge/rubric.py` — the rejection-risk rubric: one **dimension = one evaluator**, each with a written rubric prompt. MVP dimensions: placeholder/incomplete text · other-platform mentions (Android / Google Play / etc.) · misleading or inaccurate claims · price / terms / discount in description · keyword stuffing / competitor names / irrelevant keywords · beta / demo / test mentions · unauthorized contact info / links · third-party trademark/IP. Pluggable interface for future ASO / localization rubrics.
- `judge/agent.py` — pydantic-ai agent (Claude), structured `RubricVerdict` output, retry/validation.
- `judge/vision.py` — Claude vision over screenshots: placeholder images, other-platform UI / status bars, misleading or text-heavy shots, non-app content (per decision to include vision).
- `gate.py` — aggregate all verdicts → PASS / WARN / BLOCK (BLOCK on any high-severity fail); configurable `--fail-on`.
- `report.py` — human report (rich terminal + markdown) grouped by locale × dimension with quotes/refs/fixes; machine JSON; process exit code.
- `observability.py` — `logfire.configure()` + instrument pydantic-ai (auto-traces judge calls: tokens/latency/verdict) + custom spans (ingest, deterministic, eval run) + aggregate risk score.
- `cli.py` — `typer` CLI `asc-verify`: `<fastlane-path>` · `--yaml f.yaml` · `--asc-api --app-id … --key-id … --issuer-id … --key p8` · `--no-vision` · `--rubric rejection-risk` · `--format json|md` · `--fail-on warn|fail` · `--guidelines <path>` (offline copy override) · `--dry-run` (cost estimate).

## Guidelines grounding (live, session-cached)
- **Canonical source (the link):** `https://developer.apple.com/app-store/review/guidelines/` — the App Store Review Guidelines. The URL lives in config; the guidelines **text is never bundled or committed.**
- **Fetched at review time.** On the first judge run in a session, the tool fetches the current guidelines and extracts the metadata-relevant sections (esp. §2.3 Accurate Metadata + related). That text becomes **grounding context** for the judge, so every `guideline_ref` is a *real, current* citation — not a snapshot that rots (the stale-proof lesson), not invented.
- **Session-scoped cache only.** Held in a session temp location (system temp / gitignored), reused across verify calls *within* the session, and **re-fetched in a new session** so it never goes stale. Never persisted to the repo — which also avoids redistributing Apple's copyrighted text.
- **Offline / fetch-failure degradation (honest):** if the fetch fails (offline / page moved), deterministic checks still run and the judge runs *without* live citations, clearly flagging "guideline references unavailable (offline)" — it does **not** fabricate refs. `--guidelines <path>` supplies a local copy for offline runs.

## The eval-science backbone (what makes this a credential, not a demo)
Two honestly-separated uses of the Pydantic eval stack:
- **pydantic-ai = the judge** (production verification *and* meta-eval).
- **pydantic-evals = validating the judge.** `evals/golden/` holds a **curated golden dataset** (~30–50 real known-rejectable + known-clean metadata snippets drawn from actual App Store rejection reasons, each labeled with the correct verdict + dimension). A pydantic-evals `Dataset` runs the judge over it and reports **judge-vs-ground-truth agreement** (precision / recall / accuracy per dimension) plus a **failure taxonomy** of where the judge disagrees.
- **Pre-registered expected accuracy** (honest number recorded before running), and an honest build-log noting where the judge misses. This *is* rubric design + dataset curation + LLM-as-judge + agreement statistics — genuine substance, measurable, not asserted.

## Observability (Logfire)
Full source→gate trace: ingest span → deterministic span → per-dimension judge spans (with model, tokens, latency, verdict) → vision spans → aggregate gate span with risk score. Logfire is the demo surface: one run, one clickable trace.

## Packaging: pip-installable library that bundles a Claude skill
- The tool is a **pip-installable package** (`asc-metadata-verifier`, `src/` layout) exposing the `asc-verify` CLI (typer entry point).
- It **bundles a Claude skill** (`app-store-review-gate`) *inside the package* following the **`library-skills` convention** (tiangolo), so that `uv add asc-metadata-verifier` then `uvx library-skills` discovers and installs the skill automatically — this is what makes it "visible on library-skills.io".
- **⚠️ Open (Task 1 of the plan):** the exact bundling convention (in-package skill folder path, any `pyproject.toml` entry-point, the SKILL.md frontmatter `library-skills` reads) is **not cleanly published**. Task 1 derives it authoritatively from the `library-skills` source (github.com/tiangolo/library-skills) + a reference implementation (FastAPI's bundled skill) and records it here before any packaging code. Do NOT guess it.
- **Fallback install path (always works):** a `SKILL.md` + `install` instructions so anyone can copy the skill into `~/.claude/skills/app-store-review-gate/` manually, independent of the `library-skills` tool.
- **The skill itself:** given an app (path or ASC app id), it runs `asc-verify`, interprets the JSON report, presents the gate decision + prioritized fixes, and **refuses to proceed to `ios-fastlane-ship` on BLOCK** until resolved.

## Error handling
- Ingest: missing files/locales and ASC-API auth failures produce actionable messages, not tracebacks; partial metadata is verified for what's present with missing-required flagged.
- Judge: retry/backoff; malformed structured output → pydantic validation + retry; rate limits handled; cost cap + `--dry-run` estimate.
- Degradation: with no API key, deterministic results still render (clearly marked "LLM checks skipped"). Unreadable screenshots skip with a warning, never fail the run.
- Guidelines fetch: on failure (offline / page moved), run without live citations and flag "guideline references unavailable (offline)" — never fabricate refs; `--guidelines <path>` supplies a local copy.

## Testing
- **Always-on unit tests:** adapters (fastlane parse, yaml parse, ASC-API response mapping — mocked), deterministic checks, gate aggregation, report rendering, exit codes.
- **LLM tests = the golden meta-eval:** assert known-bad flagged / known-clean passed within a probabilistic tolerance; gated behind an API-key env so CI stays green offline.
- **Vision:** a couple of known-bad / known-good screenshot fixtures.
- **E2E:** a deliberately-flawed sample fastlane app fixture → full run → expected BLOCK with the specific findings.

## Repo & naming
- Repo: `git@github.com:vitalii-vlc/asc-metadata-verifier.git` → `~/Projects/asc-metadata-verifier`.
- Package: `asc_metadata_verifier` · CLI: `asc-verify` · bundled skill: `app-store-review-gate`.

## Phasing
- **Phase 1:** models · fastlane + YAML ingest · deterministic checks · rejection-risk LLM judge · Logfire · gate/report · CLI · golden meta-eval · **library-skills packaging (after Task 1 confirms the convention)** + fallback skill install.
- **Phase 2:** ASC-API adapter · vision judge for screenshots.

## Definition of done (Phase 1)
`uv run asc-verify <sample-flawed-fastlane>` → BLOCK with quoted, guideline-referenced findings + fixes; a Logfire trace of the run; `pydantic-evals` golden meta-eval reporting judge accuracy; `uvx library-skills` installs the bundled skill (or the documented manual fallback does); unit + meta-eval + e2e tests green; README + this spec + honest BUILD_LOG shipped.

## Pre-registration (honest estimate — to confirm before feature code)
**Estimate: 7 working-days part-time** — signed off by Vitalii 2026-08-08 (AI-generated range was ~6–9; set at 7 by the senior engineer). Split: Phase 1 ~4–5, Phase 2 ~2–3. Top risks: (1) the undocumented `library-skills` convention (Task 1); (2) ASC-API JWT auth + response shape; (3) golden-dataset curation quality (garbage labels → meaningless agreement stats); (4) vision cost/latency; (5) live-guidelines fetch reliability / Apple page-structure drift.

## Open questions
- None blocking. The single unknown (library-skills convention) is scheduled as Task 1 rather than guessed.
