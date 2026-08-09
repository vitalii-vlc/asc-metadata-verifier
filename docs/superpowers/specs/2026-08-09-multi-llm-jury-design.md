# Multi-LLM Jury — Design Spec (v2, sub-project A)

> Pre-registration commit — scope + design fixed **before** any feature code
> (honest-velocity method, mirroring the v1 spec). Date: 2026-08-09.
>
> This is the **first of five** v2 sub-projects. The others — persistence (B),
> code analyzer (C), pages analyzer (D), HTML report generator (E) — each get
> their own spec → plan → build cycle and are **out of scope here**. The jury is
> built first because it is the horizontal seam every later analyzer plugs into,
> and because it is the strongest measurable extension of the eval-science story.

**Goal:** turn the single-agent LLM judge into an opt-in **panel** ("jury") of
independently-configured judges (Claude + any OpenAI-compatible endpoint,
including self-hosted) that run concurrently, vote per (locale, dimension) and
per screenshot, and collapse to one gate verdict via a **selectable consensus
policy** — while recording every raw vote so inter-judge agreement and
jury-vs-single-judge accuracy become measurable on the golden set.

**Architecture (one line):** a `JudgePanel` of `JudgeClient`s runs async/concurrently,
each emitting a `RubricVerdict`; a pluggable `ConsensusPolicy` aggregates the votes
into the same `RubricVerdict` the gate already consumes, plus a `PanelVerdict` that
preserves the raw votes; unconfigured collapses to a 1-judge Claude panel that is
byte-identical to v1.

**Tech stack (unchanged from v1):** Python (uv) · pydantic-ai (multi-provider judges,
structured output) · pydantic (models) · pydantic-evals (jury meta-eval) · logfire
(per-judge tracing) · pyyaml (judges config) · typer + rich (CLI) · asyncio (concurrency).
No new third-party dependency is required — pydantic-ai already speaks Anthropic and
any OpenAI-compatible base URL.

---

## Global constraints
- **Honesty bar (hard, inherited from v1):** no fabricated findings, no invented
  `guideline_ref`. Additionally: **never fabricate a vote.** A judge that abstains,
  errors, is unavailable, or cannot see an input is recorded as such and **excluded
  from the tally** — it is never silently counted as agreeing. Reported agreement
  statistics and accuracy numbers are computed from real runs, never asserted.
- **Purely additive / backward compatible:** with no jury configuration and only
  `ANTHROPIC_API_KEY` present, the tool builds a **1-judge Claude panel** whose
  `verdicts` output is identical to v1. Existing tests and CLI behavior must not change.
- **Secrets by reference only:** `judges.yaml` names environment variables
  (`api_key_env: OPENAI_API_KEY`); it never contains a raw key. Same security posture
  as v1 (`.gitignore` blocks `.env`, `*.p8`, caches).
- **Offline-safe:** consensus policies, config loading, panel orchestration, and
  failure handling are fully testable with injected fake models (`TestModel`/
  `FunctionModel`) and monkeypatched env — **CI stays green with no API keys and no
  network.** Real-model behavior lives behind key-gated tests.
- **Determinism first (inherited):** the panel only runs where v1 already spent an LLM
  call; deterministic checks are untouched and never juried.
- **Default judge model:** `claude-sonnet-5` (unchanged), i.e. the default 1-judge panel.

## Non-goals (this sub-project)
- HTML report generator (sub-project E). Markdown/JSON gain the panel data; rich
  visualization of votes/diffs is E's job.
- Run persistence / history / cross-run diffing (sub-project B).
- Code analyzer (C) and pages analyzer (D).
- **Confidence calibration.** We *measure* whether self-reported confidence is
  miscalibrated (via the meta-eval); we do not correct it.
- **Per-provider prompt tuning.** All judges receive the same rubric prompt and
  grounding; provider-specific prompt optimization is a later concern.
- Auto-selecting or ranking judges. The user configures the panel; the tool runs it.

---

## Data flow (v1 steps unchanged before and after the judge step)
```
source ─▶ ingest ─▶ AppMetadata ─▶ deterministic ─▶ guidelines ─┐
                                                                 ▼
                                   JudgePanel (N JudgeClients, async, Semaphore-capped)
                                     per (locale,dimension): N text votes  ┐
                                     per screenshot:         M vision votes ┼─▶ ConsensusPolicy
                                                                            │      │
                                                                            │      ▼
                                                        aggregated RubricVerdict + PanelVerdict
                                                        (raw votes + agreement)
                                                                            │
                                              verdicts = [p.consensus ...]  ▼
                                                        gate (unchanged) ─▶ report ─▶ exit code
        └──────── every judge call + panel + gate traced in Logfire ────────┘
        (offline) evals/jury_eval: per-judge accuracy · inter-judge κ · jury-vs-single lift
```

## Components (module map)

### New modules
- **`judge/prompts.py`** — the prompt/grounding builders extracted verbatim from v1's
  `agent.py` (`_grounding_for`, `_format_fields`, `_build_prompt`) and `vision.py`, so
  every `JudgeClient` shares one prompt construction path. No behavior change vs v1 —
  a pure move + shared import.
- **`judge/client.py`** — `JudgeClient`: wraps exactly one model as a pydantic-ai
  `Agent` with `output_type=RubricVerdict`. Attributes: `name: str`,
  `supports_vision: bool`, `available: bool`. Methods:
  - `async run_text(dimension, locale_meta, grounding) -> JudgeVote`
  - `async run_vision(screenshot, dimension, grounding) -> JudgeVote`
  Each method builds the shared prompt, runs the agent (`await agent.run(...)`), and
  applies the **same v1 honesty post-processing** (authoritatively stamp `locale`,
  `dimension`/`field`; force `guideline_ref=None` when the grounding actually used is
  empty). It **catches its own exceptions** and returns a `JudgeVote(status="error",
  error=<truncated msg>)` — it never raises into the panel. A non-vision client asked
  to judge a screenshot returns `JudgeVote(status="not_applicable")` without a call.
- **`judge/config.py`** — `JudgeSpec` (pydantic model, see schema below) plus:
  - `load_judges(path: Path) -> JudgeSet` — parse `judges.yaml`, validate, resolve each
    `api_key_env` against `os.environ`. A spec whose `api_key_env` is set-but-missing
    **and** has no `base_url` → `available=False` (recorded, skipped at run time). A
    spec with a `base_url` may be available without a key (local servers often ignore it).
  - `judges_from_cli(specs: list[str]) -> list[JudgeSpec]` — parse the `--judge`
    mini-syntax. CLI specs are appended to (and can override, by `name`) the file's set.
  - Raises `JudgeConfigError` (actionable message, no traceback) on malformed yaml,
    unknown provider, duplicate judge names, or an empty resulting panel.
- **`judge/consensus.py`** — `ConsensusPolicy` protocol + four implementations +
  `POLICIES: dict[str, ConsensusPolicy]` registry. Signature:
  `aggregate(votes: list[JudgeVote], *, locale, dimension, field) -> tuple[RubricVerdict, float]`
  returning the consensus verdict and the agreement fraction. See "Consensus policies".
- **`judge/panel.py`** — `JudgePanel(clients, policy, max_concurrency)`:
  - `async judge_all(meta, guidelines, dimensions) -> list[PanelVerdict]` — for every
    (locale, dimension) [text] and every (screenshot, vision-dimension) [vision], gather
    the clients' votes concurrently under an `asyncio.Semaphore`, then apply `policy`.
  - `run_panel(...) -> list[PanelVerdict]` — sync wrapper (`asyncio.run`) for the CLI.
  - The single-judge case is a panel of one; there is exactly one orchestration path.
- **`evals/jury_eval.py`** — the jury meta-eval (see "Eval-science").

### Changed modules
- **`judge/agent.py`** — `_grounding_for`/`_format_fields`/`_build_prompt` move to
  `prompts.py` (re-exported for import stability). `build_judge` stays (a `JudgeClient`
  uses the same `Agent` construction, incl. `defer_model_check=True` and the
  `anthropic:`/OpenAI-compatible model reference). `judge_field(...)` is kept as a thin
  shim that builds a 1-judge panel and returns `[p.consensus for p in panels]`, so the
  existing signature, tests, and `cli.judge_field` monkeypatch seam keep working.
- **`judge/vision.py`** — same treatment: prompt builders shared; `judge_screenshots(...)`
  kept as a 1-judge-panel shim preserving the `cli.judge_screenshots` seam.
- **`models.py`** — add `JudgeVote` and `PanelVerdict` (below). `GateReport` gains
  `panels: list[PanelVerdict] = Field(default_factory=list)`. `verdicts` is unchanged
  in meaning (now `= [p.consensus for p in panels]`) so the gate and v1 JSON consumers
  are unaffected; `panels` is additive.
- **`gate.py`** — `evaluate(...)` gains an optional `panels: list[PanelVerdict] | None`
  parameter, passed straight through onto the returned `GateReport`. Classification
  logic (`_verdict_level`, `_finding_level`, thresholds) is **unchanged** — it still
  reads `verdicts`.
- **`report.py`** — markdown gains, per non-trivial panel, a compact one-liner:
  `panel: 3 judges → 2 fail / 1 warn (majority_severe ⇒ fail); agreement 0.67`. JSON
  already round-trips the new fields via `model_dump_json`. Full vote visualization is
  sub-project E.
- **`cli.py`** — new options on `verify` and `run_verify`: `--judges <file>`
  (path to `judges.yaml`), `--judge <spec>` (repeatable ad-hoc judge), `--consensus
  <policy>` (one of the four names; overrides the file's default), `--max-concurrency
  <int>` (default 8). Wiring: build the `JudgeSet` from file + CLI, build the panel,
  call `run_panel`; the vision panel reuses the same clients. Preserve the existing
  monkeypatch seams and the no-key/`--dry-run` skip paths. A `JudgeConfigError` is
  caught and rendered like `IngestError` (message + exit code 2, no traceback).
- **`observability.py`** — a `panel` span wrapping per-unit spans, each with a nested
  per-judge span carrying model name, latency, token usage (when the provider reports
  it), and the vote's verdict/status.

## Data model (the crux)
```python
JudgeStatus = Literal["voted", "abstained", "error", "not_applicable"]
#   voted          — a real structured verdict was produced (counts in the tally)
#   abstained      — the model declined / returned no usable verdict (excluded)
#   error          — the call raised or timed out (excluded; `error` populated)
#   not_applicable — a non-vision judge on a screenshot unit (excluded)

class JudgeVote(BaseModel):
    judge: str                              # judge name from config
    status: JudgeStatus
    verdict: RubricVerdict | None = None    # present iff status == "voted"
    error: str | None = None                # present iff status == "error"
    latency_ms: float | None = None

class PanelVerdict(BaseModel):
    locale: str
    dimension: str
    field: str
    votes: list[JudgeVote]                  # ALL configured judges, voters and non-voters
    consensus: RubricVerdict                # the gate consumes this
    policy: str                             # consensus rule name that produced it
    agreement: float | None                 # fraction of VOTERS whose verdict == consensus
```
`GateReport.panels: list[PanelVerdict]` is added; `GateReport.verdicts` remains
`list[RubricVerdict]` and equals `[p.consensus for p in panels]`.

## Config schema (`judges.yaml`)
```yaml
consensus: majority_severe          # optional; default policy for this set. --consensus overrides.
judges:
  - name: claude                    # required, unique
    provider: anthropic             # required: anthropic | openai (openai = any OpenAI-compatible)
    model: claude-sonnet-5          # required
    api_key_env: ANTHROPIC_API_KEY  # optional (name of the env var, never the key)
    base_url:                       # optional; set for self-hosted / OpenAI-compatible endpoints
    vision: true                    # optional, default false
  - {name: gpt4o, provider: openai, model: gpt-4o, api_key_env: OPENAI_API_KEY, vision: true}
  - {name: local-llama, provider: openai, model: llama3.1:70b, base_url: http://localhost:11434/v1, vision: false}
```
- **`JudgeSpec` fields:** `name: str`, `provider: Literal["anthropic","openai"]`,
  `model: str`, `api_key_env: str | None`, `base_url: str | None`, `vision: bool = False`.
- **Provider mapping:** `anthropic` → pydantic-ai `anthropic:<model>`; `openai` →
  `OpenAIModel(model, base_url=..., api_key=<resolved>)`, which covers OpenAI proper and
  every OpenAI-compatible server (Ollama, vLLM, LM Studio, LocalAI, OpenRouter, …).
- **`--judge` mini-syntax:** `name=provider:model[@base_url]` (e.g.
  `local=openai:llama3.1@http://localhost:11434/v1`); a bare `provider:model` gets an
  auto-generated name. Vision defaults to false for CLI judges (set it in the file when
  needed). CLI judges append to the file set; a CLI judge whose `name` matches a file
  judge replaces it.
- **Validation errors** (→ `JudgeConfigError`): malformed yaml; missing required field;
  unknown provider; duplicate `name`; empty final panel.

## Consensus policies
Severity ordering for comparison: **fail (2) > warn (1) > pass (0)**; within a verdict,
detail severity **high > medium > low**. Every policy operates on the **voted subset**
(`status == "voted"`); abstain/error/not_applicable votes are excluded from the tally but
retained in `PanelVerdict.votes`. If the voted subset is empty, `consensus` is a
`pass`/`low`/`confidence=0.0` verdict flagged in its `rationale` as "no judge voted", and
`agreement` is `None` (the panel span records this loudly; see failure handling).

The aggregated `RubricVerdict` copies its `offending_quote`, `rationale`, `guideline_ref`,
and `suggested_fix` from the **highest-confidence voter whose verdict equals the consensus
verdict** (so the quote/rationale can never contradict the chosen verdict). Aggregated
`severity` = the max detail-severity among those matching voters; aggregated `confidence`
= the mean confidence among them. `agreement` = (matching voters) / (voters).

| name | rule for the consensus verdict |
|---|---|
| **`majority_severe`** *(default)* | The plurality verdict among voters. On a tie, choose the **more severe**. |
| **`most_severe`** | The **maximum** verdict any voter gave (max recall / strictest). |
| **`unanimous`** | Escalate to a level only if **all** voters are ≥ it: `fail` iff all voted `fail`; else `warn` iff all voted ≥ `warn`; else `pass` (max precision / most permissive). |
| **`confidence_weighted`** | For each verdict value, sum the confidences of voters who chose it; pick the max-sum verdict; tie → more severe. **Honesty caveat (shipped in the docstring + report):** LLM confidence is uncalibrated; the meta-eval reports whether this actually beats `majority_severe` rather than assuming it. |

## Concurrency & failure handling
- The panel gathers votes with `asyncio.gather`, bounded by a single global
  `asyncio.Semaphore(max_concurrency)` (default 8) shared across all judges × units, so
  a large panel over many locales/dimensions/screenshots cannot open unbounded
  connections. Each `JudgeClient` call has a per-call timeout; a timeout is an `error`
  vote.
- A judge that errors on one unit **still votes on other units** — errors are per-call.
- **All voters failing/unavailable for a unit** produces the empty-tally `consensus`
  above and is surfaced loudly (Logfire span attribute + a `report.py` note). This is
  **distinct** from "no judges configured / no key present", which remains the v1
  deterministic-only skip (`llm_skipped = True`).
- **Unavailable judges** (an `api_key_env` that is set-but-missing and no `base_url`) are
  **omitted at panel-build time**, each with a single `judge <name> unavailable (<ENV>
  unset)` stderr note; they do **not** appear in `PanelVerdict.votes` — the votes list
  names only judges that actually ran. If this leaves **zero** available judges, the run
  takes the v1 deterministic-only skip (`llm_skipped = True`) rather than building an
  empty panel. (`abstained` is therefore a *runtime* status only — a judge that ran and
  declined — never a stand-in for an unavailable one.)

## Backward compatibility (exact)
- No `--judges`, no `--judge`, `ANTHROPIC_API_KEY` set → the CLI builds a 1-judge Claude
  panel with the default model. `report.verdicts` is identical to v1; `report.panels`
  has one `PanelVerdict` per unit, each with a single `voted` vote.
- `--dry-run` and the no-key skip path are unchanged: no panel is built, deterministic +
  gate only.
- The `cli.judge_field` / `cli.judge_screenshots` / `cli.get_guidelines` monkeypatch
  seams used by the offline e2e test still exist and still work (the shims route through
  the panel with a single injected model).

## Observability (Logfire)
`panel` span (n_judges, policy, max_concurrency) → per-unit span (locale/dimension or
screenshot) → per-judge span (model, latency_ms, tokens when reported, status, verdict).
The demo remains "one run, one clickable trace" — now showing the whole jury deliberating.

## Testing
- **Consensus policies** — pure unit tests over synthetic `list[JudgeVote]`: majority,
  every tie case, unanimous escalation boundaries, most_severe, confidence weighting,
  empty-voter-set, all-abstain, mixed error/abstain/not_applicable exclusion, and the
  representative-field selection (quote matches the chosen verdict).
- **Config loader** — tmp `judges.yaml` + monkeypatched env: happy path, secret
  resolution, missing-key→unavailable, base_url-without-key→available, `--judge`
  mini-syntax parse, CLI-overrides-file-by-name, and every `JudgeConfigError` case.
- **Panel orchestration** — a panel of injected `FunctionModel`s returning scripted
  verdicts: concurrency (semaphore cap respected), per-call error isolation (one judge
  raises, others still vote), vision `not_applicable` for non-vision judges, empty-tally
  path. No network, no keys.
- **Backward-compat** — the existing v1 judge/gate/e2e tests pass unchanged; an added
  test asserts the 1-judge-panel `verdicts` equal what v1 produced for the same inputs.
- **Jury meta-eval** — key-gated (skips offline), plus an offline test that runs the
  agreement/accuracy math over a fixed synthetic vote matrix so the statistics code
  itself is covered without models.
- **E2E** — extend the flawed-app fixture run with a 2-judge injected panel and assert
  the panel data reaches the JSON report and the gate status is unchanged from the
  single-judge run for that fixture.

## Eval-science (the credential — measured, not asserted)
`evals/jury_eval.py`, gated behind API keys:
1. Run **each configured judge individually** over the 44-case golden set → per-judge
   precision / recall / accuracy per dimension (reuses the v1 multi-label ground truth
   and the existing scoring in `meta_eval.py`).
2. Compute **inter-judge agreement**: pairwise agreement rates + **Fleiss' κ** across
   judges per dimension (κ implemented and unit-tested against a known worked example).
3. Compute **jury accuracy under each of the four policies** vs the **best single
   judge**, on the same cases → the ensemble-lift question.
4. **Pre-register the hypothesis** ("an ensemble beats the best single judge on
   rejection-risk agreement") in the build log **before** running, and report the honest
   result — **including "no lift" if that is what the data shows.** A null result is a
   valid, publishable finding and must not be massaged.

## Repo & naming
- Same repo: `~/Projects/asc-metadata-verifier`. Branch: `feat/multi-llm-jury`.
- New public config artifact: `judges.example.yaml` (committed; references env vars only,
  contains no secrets) so users have a working template.

## Definition of done
`asc-verify --judges judges.yaml <fastlane>` drives a concurrent panel of ≥2 providers;
`--consensus` switches among the four policies; the no-jury default is byte-identical to
v1; a failed/unavailable judge degrades-and-records without killing the gate; panel votes
appear in the JSON report and in a Logfire trace; `evals/jury_eval.py` reports per-judge
accuracy, inter-judge Fleiss' κ, and jury-vs-single lift on the golden set; unit +
offline + e2e tests green with no keys; `judges.example.yaml`, README, and an honest
BUILD_LOG entry shipped.

## Pre-registration (honest estimate — to confirm before feature code)
**Estimate: 3–4 working-days part-time.** Split: panel/client/config/consensus core
~1.5–2 (the bulk, but well-bounded and mostly offline-testable); CLI + report + observability
wiring ~0.5–1; jury meta-eval + κ + honest write-up ~1. Top risks: (1) async orchestration
+ semaphore correctness under injected-model tests; (2) OpenAI-compatible/self-hosted
provider construction differences via pydantic-ai (base_url + optional key); (3) keeping
the 1-judge-panel path byte-identical to v1; (4) getting the consensus edge cases (ties,
empty tally, mixed non-voters) provably right; (5) the null-result discipline in the
meta-eval (report no-lift honestly).

## Open questions
- None blocking. The self-hosted provider wiring (risk 2) is confirmed available in
  pydantic-ai via an OpenAI-compatible `base_url`; the plan validates it against a real
  local endpoint if one is reachable, otherwise against a mocked OpenAI-compatible server.
