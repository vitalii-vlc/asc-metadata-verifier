# BUILD_LOG — asc-metadata-verifier

## Task 13 — Golden dataset + judge meta-eval

### Pre-registration (written BEFORE any real-model run)

This section is pre-registered: it states the methodology and the expected
outcomes **before** the judge has ever been run against a real model on the
golden set, so the later real actuals (Task 15) cannot be back-fitted to a
post-hoc story.

#### Dataset

- `src/asc_metadata_verifier/evals/golden/cases.jsonl` — **44 labeled cases**.
  - **30 positive cases** (`expected_verdict` ∈ {warn, fail}) covering all 8
    rubric dimensions: `placeholder_text`(4), `other_platform_mentions`(4),
    `misleading_claims`(4), `price_terms_in_description`(3),
    `keyword_stuffing`(4), `beta_demo_mentions`(4), `third_party_trademark`(4),
    `unauthorized_contact_links`(3). Every dimension has ≥3 positives.
  - **14 clean controls** (`expected_dimension="none"`, `expected_verdict="pass"`),
    each engineered to *stress a specific judge* into a false positive it must
    resist — e.g. "expandable/finished" (vs placeholder), Apple-only device
    names and "windowed" (vs other-platform), "feel free"/"freedom"/"no
    subscriptions" (vs price terms), exam "practice tests" and an "Alpha" mascot
    (vs beta/demo), open-standard protocol names "CalDAV/IMAP" (near-brand tokens
    vs trademark), and a hedged near-superlative "one of the easiest ways" (vs
    misleading claims). *(The last two controls were strengthened in Fix round 1.)*
  - **4 cases carry MULTI-LABEL ground truth** (`also_valid_dimensions`) — see
    the Fix round 1 section below.
- **Honesty bar.** Every case is a realistic **synthetic** example grounded in
  the 8 rubric dimensions and the real App Store Review Guidelines §2.3
  (Accurate Metadata) / §5.2 (Intellectual Property). **No case is claimed to be
  a verbatim quote from a specific rejected app.** `source_note` states the
  guideline-category rationale, not a provenance claim. Labels were kept
  unambiguous by construction: genuinely borderline framings (e.g. the brief's
  suggested "free trial available in-app") were deliberately **excluded** in
  favor of clearly-clean lexical stressors ("feel free", "freedom"), because a
  wrong label silently corrupts every downstream statistic. A generator
  (`gen_golden.py`) asserts label coherence (`none`↔`pass`, positive↔flagged),
  no duplicate texts, valid fields, and ≥3 positives per dimension.

#### Meta-eval methodology (implemented)

- **Full dimension × case grid, one-vs-rest.** For each of the 44 cases the
  judge is run on **all 8 dimensions** (not only the labeled one). This is the
  sounder choice over "each case vs only its own dimension" because it is the
  *only* way to observe **cross-dimension false positives** (a clean control or
  a price case wrongly tripping a different dimension). Grid size = 44 × 8 = 352
  judge calls.
- **No silent caps.** Offline (FunctionModel) the full grid runs for free and
  nothing is skipped. The real-model path is the same 352 calls, **gated behind
  `ANTHROPIC_API_KEY`**; it is the only bound and it is a hard key gate, not a
  sampling cap.
- **Flag semantics:** judge verdict `warn`/`fail` = "flagged", `pass` = "not
  flagged". Ground truth for a (case, dimension) cell is flagged iff the case's
  `expected_dimension` equals that dimension **and** the case is a positive.
  *(Refined in Fix round 1 to be multi-label: a flag on a genuinely-present
  secondary dimension is an accepted detection, not a false positive — see below.)*
- **Per dimension D:** `precision = TP/(TP+FP)`, `recall = TP/(TP+FN)`.
  Zero-denominator convention (documented): reported as **0.0** (sklearn's
  default `zero_division`), so a judge that never flags D is not rewarded with a
  misleading precision of 1.0.
- **Accuracy** is per-**case** binary detection matching the label's class: a
  positive case is correct iff the judge flags its labeled dimension; a clean
  control is correct iff the judge flags **no** dimension. Severity-tier
  mismatches and extra cross-dimension flags do **not** change this binary
  number but **are** recorded in the failure taxonomy.
- **Failure taxonomy** (`dict[category → list[FailureRecord]]`), each record
  carrying `case_name`, `dimension`, `expected_verdict`, `got_verdict`, a text
  snippet, and a `detail` string:
  - `false_negative` — a positive case's labeled dimension was not flagged.
  - `false_positive` — a dimension flagged where it should not be (clean control
    flagged anywhere, or a positive case flagged on an extra wrong dimension that
    is neither the primary label nor an `also_valid` secondary).
  - `wrong_dimension` — labeled dimension missed but some other off-label
    (non-`also_valid`) dimension flagged.
  - `wrong_severity` — labeled dimension flagged but at the wrong verdict tier
    (e.g. expected `warn`, judged `fail`).

#### Pre-registered expectations (targets, NOT results)

- **Target: ≥ 0.80 per-dimension recall and ≥ 0.80 accuracy overall** for the
  real Anthropic judge on this set.
- **Easiest** dimensions (expect highest recall/precision): lexically explicit
  ones — `other_platform_mentions` (Android/Google Play), `placeholder_text`
  (lorem ipsum/TODO), `price_terms_in_description` ($/%/sale).
- **Hardest** (expect the most misses / lowest precision): the judgment-heavy
  ones — `misleading_claims` (requires reasoning about backability) and
  `third_party_trademark` (requires recognizing marks and authorization). The
  clean controls most at risk of a false positive are the price "free/freedom"
  idioms and the Apple-only-devices other-platform control.
- These are **predictions to be tested**, not measurements.

#### Honest status of the real-model run

- **The real-model meta-eval has NOT been run in this dev environment** — there
  is no `ANTHROPIC_API_KEY` here. Only the **offline FunctionModel-stub** harness
  validation below has been executed. **No real-model accuracy numbers are
  recorded or fabricated.** The gated test `test_real_model_meta_eval`
  (`@pytest.mark.skipif` on `ANTHROPIC_API_KEY`) is **skipped**; Task 15 will run
  it and append the real per-dimension actuals under a "Real-model actuals"
  heading below.

#### Offline harness validation (stub runs only — deterministic, no network)

These numbers validate the *aggregation logic*, using deterministic
`FunctionModel` stubs. They are **not** a measure of the real judge.

| Stub | accuracy | key taxonomy signal |
|------|----------|---------------------|
| `oracle` (perfect judge, keyed on labels) | **1.0** | 0 failures; precision=recall=1.0 for all 8 dims |
| `always_pass` (never flags) | **0.3182** (14 controls / 44) | 30 `false_negative`; recall=0.0 all dims |
| `always_fail` (flags every dim) | **0.6818** (30 positives detected / 44) | 318 `false_positive`, 8 `wrong_severity`, 4 accepted_secondary |

- `always_fail` false-positive count **318** = 14 controls × 8 + 30 positives × 7
  − 4 accepted secondary flags (the 4 `also_valid` cells), confirming both
  cross-dimension FP capture *and* the multi-label exclusion. The 8
  `wrong_severity` records are exactly the 8 `warn`-labeled positives judged as
  `fail`. *(Was 322 before Fix round 1's multi-label rule.)*

#### TDD evidence

- RED: `uv run pytest tests/test_meta_eval.py` → `ModuleNotFoundError: No module
  named 'asc_metadata_verifier.evals.dataset'` (before implementation).
- GREEN: `uv run pytest` → **141 passed, 2 skipped** at the initial commit; **143
  passed, 2 skipped** after Fix round 1 (2 multi-label tests added). The 2 skips
  are the two `ANTHROPIC_API_KEY`-gated tests. `uv run ruff check .` →
  **All checks passed!**

---

### Fix round 1 — multi-label ground truth (methodology upgrade)

**Problem the audit found.** Single-label ground truth (one `expected_dimension`
per case) mis-scored a *correct* judge. Four cases carry genuine SECOND-dimension
signal, and flagging it is right, not an error — but full-grid one-vs-rest
counted those correct flags as false positives, depressing precision on
`third_party_trademark` (the dimension the pre-registration calls hardest). A
worked example: competitor brand names in a keyword-stuffing case (`evernote,
onenote, notion, …`) ARE genuinely third-party trademarks.

**Upgrade (a real eval-science improvement, not a patch).** The label schema
gains an optional `also_valid_dimensions: list[str]` (default `[]`) — dimensions
OTHER than `expected_dimension` that are genuinely present, so flagging them is
acceptable. Set for exactly 4 cases:

| case | primary label | `also_valid_dimensions` | why |
|------|---------------|-------------------------|-----|
| `15-keyword_stuffing` (`…evernote,onenote,notion…`) | keyword_stuffing | `third_party_trademark` | brand names are also marks |
| `17-keyword_stuffing` (`…instagram,snapchat,tiktok,facebook…`) | keyword_stuffing | `third_party_trademark` | brand names are also marks |
| `25-unauthorized_contact_links` (`…message us on WhatsApp…`) | unauthorized_contact_links | `third_party_trademark` | "WhatsApp" is a mark |
| `24-unauthorized_contact_links` (`Get credits cheaper on our website…`) | unauthorized_contact_links | `price_terms_in_description` | "cheaper" is a price term |

**Scoring rule (exact — this is how also_valid cells are counted).** A judge flag
(`warn`/`fail`) on dimension D for a case is a **false positive** iff
`D != expected_dimension AND D not in also_valid_dimensions`. For a
(case, dimension) cell where `dimension ∈ also_valid_dimensions`:

- the cell is **excluded from that dimension's TP/FP/FN/TN entirely**;
- a **flag** there is tallied in `MetaEvalReport.accepted_secondary_detections`
  (an accepted detection — never TP, never FP);
- a **non-flag** there is simply ignored (never FN — recall is unaffected).

**Recall is unchanged**: TP/FN arise only from *primary-label* cells, so recall
stays keyed on `expected_dimension`. `wrong_dimension` likewise now ignores
`also_valid` flags (a genuine secondary detection is not a mis-attribution).

**Why this is a strength, not leniency.** Real store metadata routinely trips
multiple guideline dimensions at once; single-label ground truth would score a
*more thorough* judge as *less precise*. Multi-label ground truth measures the
judge against reality. Concretely, under the counterfactual single-label rule the
3 trademark secondary flags would drag `third_party_trademark` precision to
`4/(4+3) = 0.571`; multi-label keeps a correct judge at `1.0`. This is proven by
`test_also_valid_flag_is_accepted_not_false_positive` (a stub that flags every
case's `also_valid` dimension yields `accepted_secondary_detections == 4`,
`false_positive == []`, `third_party_trademark` precision `1.0`).

**Denominator guard (minor).** On the real-model path (`model=None`),
`run` now asserts the number of scored cases equals the golden line count and
that `report.failures` is empty — because `Dataset.evaluate_sync` shunts a task
that RAISED (e.g. a failed real-model call) into a separate `failures` list,
which would otherwise silently shrink the denominator and inflate rates in
Task 15. A shortfall now raises `RuntimeError` instead of quietly under-counting.

---

## Build actuals (Task 15 — end of Phase 1)

This section is written AFTER the Phase 1 implementation, as the honest counterpart
to the pre-registration above. It records what actually happened, not what was
planned — including the parts that didn't go cleanly.

### Approach

Phase 1 was scoped as **15 tasks** (`docs/superpowers/plans/2026-08-08-asc-metadata-verifier.md`),
built **TDD** (RED before GREEN, per-task), **subagent-driven**: each task ran as an
implementer sub-agent producing a report, then a separate reviewer sub-agent audited
the diff against the task's spec before the task was marked complete — a genuine
spec+quality **review gate**, not a rubber stamp (see the fix rounds below, and
Task 8's reviewer literally fetching the live Apple guidelines page to check the
extraction logic against real markup, and Task 14's reviewer inspecting the actual
built wheel rather than trusting the packaging config). The pre-registered estimate
was **7 working-days part-time**, signed off by the maintainer on 2026-08-08 (design spec,
`docs/superpowers/specs/2026-08-08-asc-metadata-verifier-design.md:100`; AI-generated
range was ~6–9, set at 7 by the maintainer). This log does not fabricate a
measured elapsed-time actual against that estimate — the SDD ledger
(`.superpowers/sdd/2026-08-08-asc-metadata-verifier/progress.md`) records task-by-task
outcomes, not wall-clock time, so no elapsed-days number is claimed here.

### Fix rounds that actually occurred (evidence the review gate worked)

Of 15 tasks, **6 required a fix round** after review before being marked complete;
9 passed review clean on the first pass. Recording the fix rounds honestly — this is
the review gate doing its job, not a defect in the process:

- **T5 (deterministic checks):** review flagged that the placeholder patterns
  (`TODO`, `XXX`, `FIXME`, `placeholder`) were unanchored, causing substring false
  positives (e.g. "Maxxx", "placeholders", "expandable options"). The maintainer made an
  explicit execution-time decision (via `AskUserQuestion`) to **anchor all four
  patterns with `\b…\b`** word boundaries; the plan doc was revised and the fix
  committed (`0d3e439`, `e9ce537`). This same anchoring is what Task 15's flawed
  fixture depends on (see "Honest limitations" below for where it still isn't free
  of edge cases — see the fixture-authoring note further down).
- **T7 (YAML ingest):** review found malformed/non-dict YAML input (e.g. `locales`
  as a list or string, screenshot values as bare strings) raised a raw Python
  exception (`AttributeError`) instead of an `IngestError`. Fixed to raise
  `IngestError` uniformly, with added `isinstance` guards and a `UnicodeDecodeError`
  catch (`d35d1cd`).
- **T8 (live guidelines source):** review **fetched the real Apple guidelines
  page** and found two real problems: (1) `sections["2.3"]` came back empty
  because the real markup splits the heading number from its title with an inline
  tooltip `<span>`/`<img>` inside the `<strong>` tag; (2) `<script>`/`<style>` tag
  *bodies* (not just the tags) were leaking ~12% raw JS/CSS text into the extracted
  guideline text. Both fixed (bare-section-number line-merging heuristic; strip
  script/style bodies before tag-stripping) and re-verified against a second live
  fetch (`5b15c12`).
- **T9 (judge agent + rubric):** review flagged that the default/env model
  construction path (`build_judge()` with `model=None`, `ASC_JUDGE_MODEL` env var,
  `defer_model_check=True`) had no test coverage. Added keyless-construction and
  env-precedence tests, plus tightened the honesty guarantee so `guideline_ref` is
  forced `None` whenever the grounding text actually used for a call is empty — not
  only when `guidelines.available` is `False` (`b48f85e`).
- **T11 (gate + report):** review found the locale×dimension markdown grouping
  logic had no test actually exercising **more than one group** — added a real
  multi-group test, plus fixed pass-verdicts not surfacing their `field` (`6bdcb5e`).
- **T13 (golden dataset + meta-eval):** review (by an Opus reviewer who
  hand-audited 23/44 case labels) found that 4 positive cases carry genuine
  second-dimension signal (e.g. competitor brand names in a `keyword_stuffing` case
  are *also* third-party trademarks), and single-label ground truth was scoring a
  *correct* judge flag on that second dimension as a false positive — depressing
  `third_party_trademark` precision to 0.571. Fixed by upgrading to **multi-label
  ground truth** (`also_valid_dimensions`) for exactly those 4 cases, which restores
  precision to 1.0 for a judge that correctly flags both dimensions, without
  touching recall (`69678da`).

The other 9 tasks (T1–T4, T6, T10, T12, T14, and T15 itself) passed review with no
fix round, or (T15) required no pipeline fix at all — see below.

### Design decisions to surface for review

Two decisions were made during execution, where the plan was silent or ambiguous,
and are being surfaced explicitly here rather than left buried in commit history:

1. **Deterministic-finding → gate-level mapping.** The plan specified that
   `evaluate()` takes `deterministic_findings` but did not pin the exact
   block/warn logic for them. Task 11's controller decision (recorded live in the
   SDD ledger) was: `over_limit` and `missing_required` are **BLOCK-worthy**
   (they are objective, guaranteed App Store rejections — no judgment call
   involved), while `placeholder` and `malformed_url` are **WARN-worthy**
   (heuristic signals that can have false positives). This is what makes
   `--dry-run` / no-`ANTHROPIC_API_KEY` mode still catch hard rejections even with
   the judge fully skipped — worth revisiting if the WARN/BLOCK split ever
   needs different risk tolerance (e.g. treating `malformed_url` as BLOCK too).
2. **Placeholder patterns anchored with `\b…\b`.** Per the maintainer's T5 execution-time
   decision above — flagged here again because it is a live tradeoff: word-boundary
   anchoring eliminates substring false positives (e.g. "placeholders"), but it
   also means a placeholder token embedded without word boundaries (rare, but e.g.
   a token concatenated with punctuation the regex engine doesn't treat as a
   boundary) could in principle be missed. No such miss has been observed in
   practice; noted for awareness, not as a known bug.

### Task 15 itself: the e2e run, and the one thing it actually caught

Building the flawed fixture (`tests/fixtures/fastlane_flawed/`) followed the same
RED→GREEN discipline: `tests/test_e2e.py` was written first and confirmed to fail
by collection error (`ERROR: file or directory not found: tests/test_e2e.py`)
when the test file and fixture were temporarily moved aside, then the fixture was
authored and the test passed clean on the **first real run against the actual
pipeline** — **no pipeline code changes were needed** in `checks/deterministic.py`,
`gate.py`, `report.py`, or `cli.py`. This is genuinely different from the fix
rounds above (T5, T7, T8, T9, T11, T13), where review caught real code defects;
here the pipeline had none left to find.

The one real thing the e2e process did catch was in the **fixture itself**, not
the pipeline: the first draft of `keywords.txt` reused the clean fixture's
`"tasks,todo,planner,productivity"` keyword list, and the word "todo" — a
legitimate, realistic keyword in a task-planner app's keyword list — matched the
(correctly, per T5) anchored `\bTODO\b` placeholder pattern, producing a 5th,
unplanned `placeholder` finding on the `keywords` field and muddying the intended
"exactly 4 planted issues" story. Fixed by changing the keyword list to
`"tasks,checklist,planner,productivity,organizer"` (no fix to production code).
This is a small but real illustration of why "verify the fixture doesn't
accidentally trip an anchored pattern" (the brief's own warning) matters in
practice, not just in theory — anchored word-boundary matching is precise, but a
real-sounding word can still legitimately be a placeholder token.

### Real-model meta-eval status — HONEST

**The real-model judge meta-eval has NOT been run in this build.** There is no
`ANTHROPIC_API_KEY` in this dev environment, so both gated tests remain skipped:

```
tests/test_judge.py::test_real_model_smoke SKIPPED (requires ANTHROPIC_API_KEY)
tests/test_meta_eval.py::test_real_model_meta_eval SKIPPED
```

The pre-registered accuracy **targets** (≥0.80 per-dimension recall, ≥0.80 overall
accuracy — see the pre-registration section above) stand as targets. **No
real-model accuracy numbers — per-dimension or overall — are recorded or
fabricated anywhere in this log or the README.** Only the offline
`FunctionModel`-stub harness-validation numbers (oracle / always_pass / always_fail)
are real numbers, and they measure the aggregation *logic*, not judge quality.

**To run the real-model meta-eval later:**

```bash
export ANTHROPIC_API_KEY=sk-...
uv run pytest tests/test_judge.py::test_real_model_smoke -v      # single-call smoke test first
uv run pytest tests/test_meta_eval.py::test_real_model_meta_eval -v  # full 44x8 grid, real model
```

That run exercises the **multi-label ground-truth** scoring (Fix round 1 above —
`also_valid_dimensions` cells are excluded from TP/FP/FN and counted as
`accepted_secondary_detections` instead) and the **denominator guard** added in
that same fix round (`run()` on the real-model path asserts the scored-case count
equals the golden-set line count and `report.failures` is empty, raising
`RuntimeError` on a shortfall instead of silently under-counting and inflating
rates) — append the actual per-dimension precision/recall/accuracy and any
triggered failure-taxonomy entries under a new "Real-model actuals" heading when
that run happens.

### Honest limitations — where this tool could miss

- **Judge quality is not yet empirically measured against a real model** — only
  the offline `FunctionModel` stub harness has been exercised (see above). The
  8-dimension rubric's real-world precision/recall is unknown until the gated
  real-model meta-eval is run.
- **Guideline section-extraction is heuristic**, not a real HTML parser: it reduces
  tags to newlines and pattern-matches numbered headings. It was validated against
  a **real fetch of the live Apple guidelines page** for §2.3 specifically (Task 8's
  review round, confirmed twice), but Apple could restructure the page in a way
  that breaks the heading regex or the bare-section-number merge heuristic again;
  there is no test against the *entire* current page, only the specific markup
  shapes that were found and fixed.
- **The rubric is 8 MVP rejection-risk dimensions** (placeholder text, other-platform
  mentions, misleading claims, price terms, keyword stuffing, beta/demo mentions,
  unauthorized contact links, third-party trademark). ASO-quality and localization
  rubrics (e.g. subtitle keyword optimization, translation quality) are not built
  and are out of scope for Phase 1.
- **Vision (screenshot) judging and the App Store Connect API adapter are Phase 2**,
  not yet built. `--no-vision` is accepted by the CLI for shape stability but never
  runs anything yet either way, and there is no `--asc-api` flag.

### library-skills bundling — empirically verified, confirmed

Unlike the judge-quality items above, this one is **confirmed**, not pending:
Task 14 verified wheel inclusion of the bundled `app-store-review-gate` skill
(via `unzip -l` on the actual built wheel plus a packaging test) with **zero**
extra `pyproject.toml` config needed, and ran a **real** `uvx library-skills`
install against a fresh consumer project, confirming the skill lands in both
`.agents/skills` and `.claude/skills`. This can be stated as fact, not aspiration.

### RED/GREEN evidence (Task 15)

RED — before the fixture/test existed (reproduced by temporarily moving both aside):

```
$ uv run pytest tests/test_e2e.py -v
ERROR: file or directory not found: tests/test_e2e.py
collected 0 items
```

GREEN — after building the fixture (with one fixture-content fix, no pipeline
code change; see above) and the e2e test:

```
$ uv run pytest tests/test_e2e.py -v
tests/test_e2e.py::TestFlawedAppMarkdown::test_blocks_and_names_all_four_planted_issues PASSED
tests/test_e2e.py::TestFlawedAppJson::test_json_status_block_and_planted_items_present PASSED
2 passed in 0.83s
```

Full suite + lint:

```
$ uv run pytest
149 passed, 2 skipped   ->   151 passed, 2 skipped   (2 new e2e tests added, no regressions)

$ uv run ruff check .
All checks passed!
```

--- END PHASE 1 ---

## Phase 2

Two tasks, built on top of the Phase 1 pipeline: a live App Store Connect API
ingest adapter (T16) and a vision judge over screenshots (T17). Both land in
this branch (`feat/asc-verifier-implementation`) after Task 15's Phase 1
close-out above; the README and this log were not updated at the time each
landed, which is the honesty gap this section (and the fix wave that added
it) closes.

### T16 — App Store Connect API ingest adapter

`src/asc_metadata_verifier/ingest/asc_api.py` adds `AscApiAdapter`, a third
`IngestAdapter` implementation alongside `FastlaneAdapter`/`YamlAdapter`. It:

- Authenticates with a **JWT signed ES256** (`PyJWT` + `cryptography`'s EC
  P-256 key loading) built from an App Store Connect API key (`.p8` file,
  key id, issuer id), per Apple's documented token scheme (`kid` header,
  `iss`/`iat`/`exp`/`aud` claims, ≤20-minute TTL).
- Fetches app-info localizations, App Store version localizations, and
  screenshot asset URLs via `httpx`, and maps the JSON:API compound-document
  response shape into the canonical `AppMetadata`/`LocaleMetadata`/
  `Screenshot` models.
- Wires into the CLI as four new flags — `--asc-api-app-id`,
  `--asc-api-key-id`, `--asc-api-issuer-id`, `--asc-api-key` — selected only
  when all four are given (a partial set is a `typer.BadParameter`, not a
  silent fallback to fastlane/YAML).
- Raises `IngestError` (never a raw traceback) for an unreadable/malformed
  `.p8` key, a JWT signing failure, a network error, and 401/403/4xx/5xx
  responses from the API.

**Honesty note (unchanged from the module's own docstring): this adapter has
NOT been validated against the real App Store Connect API.** There are no
live ASC credentials in this dev environment. `tests/test_ingest_asc_api.py`
exercises it entirely against `httpx.MockTransport` responses shaped like
Apple's documented API (JSON:API `data`/`included` payloads matching the
public API reference) and a throwaway EC P-256 key generated per test run —
real JWT signing is genuinely exercised, but the actual HTTP contract (exact
response shapes, pagination behavior beyond the documented single-page
YAGNI limitation, real error payloads) is untested against a live account.

### T17 — Vision screenshot judge

`src/asc_metadata_verifier/judge/vision.py` adds a fourth judged artifact
type — screenshots, not text fields — mirroring `judge/agent.py`'s pattern:
one `pydantic_ai.Agent` with structured `RubricVerdict` output, run once per
(screenshot, vision dimension), with the image bytes attached as
**`pydantic_ai.BinaryContent`** (`media_type` derived from the image's byte
signature, never trusted from the file extension). Four vision dimensions:
`placeholder_image`, `other_platform_ui`, `misleading_screenshot`,
`excessive_text`. Same two honesty layers as the text judge — the system
prompt requires `guideline_ref` to be null when no grounding text is given,
and defensive post-processing force-nulls it whenever the grounding actually
used for that call was empty. A screenshot whose path is a remote URL, or
that is missing/unreadable/not a decodable image, is skipped with a
`logging.warning` rather than raising — judging continues with the rest.

Wired into the CLI: the vision judge runs after the text judge whenever
`--no-vision` is unset, a key/model is available, and the ingested metadata
has at least one screenshot; its verdicts are appended to the same list
passed to `evaluate()`, so vision findings gate the run exactly like text
findings.

**Honesty note (unchanged from the module's own docstring): real-model
vision quality has NOT been measured.** `tests/test_vision.py` is entirely
offline, served by a deterministic `pydantic_ai.models.function.FunctionModel`
that inspects only the *text* portion of the prompt (it cannot see pixels) —
it keys on the screenshot's filename (e.g. `bad.png` vs `good.png`) to return
a controlled fail/pass verdict. This proves the plumbing (image bytes are
genuinely attached and sent as `BinaryContent`, media type is derived from
signature not extension, locale/dimension/field stamping, the skip path for
unreadable/remote screenshots, and the honesty force-null rule) but proves
nothing about whether a real model correctly judges real screenshot content.
The gated `test_real_model_smoke` (`@pytest.mark.skipif` on
`ANTHROPIC_API_KEY`) remains skipped in this environment, same as the
text-judge and meta-eval real-model tests.

### What this means for the README's Phase 1/2 status line

The README previously stated Phase 2 (ASC-API ingest, vision judge) was "not
yet built." That was accurate when written (end of Task 15) but went stale
the moment T16/T17 landed in this same branch without a doc update — a real
documentation/code mismatch, not a design decision. The README has been
corrected (see its Status line and the `--asc-api-*`/`--no-vision` flag
docs) to state plainly: Phase 2 code is shipped and tested, but — same as
Phase 1's judge-quality caveat — neither the ASC-API adapter nor the vision
judge has been exercised against the real service/model they target. No new
accuracy or reliability numbers are claimed here; none were measured.

--- END PHASE 2 ---

## Multi-LLM Jury (sub-project A)

### Task 4 — JudgeClient (async text+vision, error-isolated, honesty-preserving)

`src/asc_metadata_verifier/judge/client.py` adds `JudgeClient`: one
configured model wrapped as an async judge that votes on a text unit
(`run_text`) and, if it supports vision, a screenshot unit (`run_vision`).
Two constructors: `from_model(name, model, *, supports_vision=False)` for
offline/injected models (used by all of `tests/test_client.py`), and
`from_spec(spec)` for a resolved `JudgeSpec` (Task 5, not yet built —
referenced only as a `TYPE_CHECKING` forward ref here, so this module
imports cleanly before Task 5 lands).

**Step 0 (provider API verification, done before writing `_model_ref`):**
ran
`uv run python -c "import importlib; m=importlib.import_module('pydantic_ai.models.openai'); print([n for n in dir(m) if 'Model' in n])"`
against the installed `pydantic-ai` (2.27.x). It printed
`OpenAIChatModel`, `OpenAIResponsesModel`, `OpenAIModelProfile`, ... —
**there is no `OpenAIModel` class in this version**; `OpenAIChatModel` is
the one that maps to the brief's "OpenAIModel or OpenAIChatModel"
instruction. `_model_ref` was written against `OpenAIChatModel(spec.model,
provider=OpenAIProvider(base_url=..., api_key=...))` accordingly. The
import did not raise `ModuleNotFoundError: openai` — the `openai` package
(2.53.0) was already resolvable in this environment, so per the brief's
conditional instruction no `openai` dependency was added to
`pyproject.toml`. **Correction (fix round 1):** an earlier version of this
note called that a "latent risk" from a fragile transitive pull; that
overstated it. `importlib.metadata.requires("pydantic-ai")` shows
`pydantic-ai` (2.27.0) itself depends on
`pydantic-ai-slim[anthropic,cli,evals,google,logfire,mcp,openai,retries,web]==2.27.0`
— i.e. `openai` arrives via **this project's own direct `pydantic-ai>=2.27.0`
dependency and its pinned, bundled `openai` extra**, not an incidental
third-party pull that could disappear underneath us. It is a stable,
intentional part of what `pydantic-ai` ships. Declaring `openai>=1.0`
explicitly in `pyproject.toml` is still optional good practice (makes the
dependency self-documenting, survives a hypothetical future `pydantic-ai`
release that drops the bundled extra) — deferred to Task 5, when
`from_spec`'s OpenAI-compatible path first gets exercised — but it is not
a reliability risk today.

Honesty stamping matches v1 exactly (verified against
`judge/agent.py::judge_field` and `judge/vision.py::judge_screenshots`
before writing `_run`): text stamps only `locale`+`dimension` (the model
reports `field` itself); vision additionally stamps `field="screenshot"`;
both force `guideline_ref=None` whenever the grounding actually used for
that call is falsy. A non-vision client's `run_vision` returns
`JudgeVote(status="not_applicable")` before building any prompt or
touching the agent — `tests/test_client.py`'s
`test_non_vision_client_run_vision_is_not_applicable_without_a_call`
asserts the injected model function was never invoked. Any exception
raised by `agent.run(...)` is caught in the single shared `_run` helper
and converted to `JudgeVote(status="error", error=str(exc)[:300])` — never
re-raised, so one judge's failure can't take down a panel run (Task 6+).

`tests/test_client.py` is entirely offline, driven by the same
`FunctionModel` pattern as `tests/test_judge.py`, using `asyncio.run(...)`
to exercise the async methods directly (no `pytest-asyncio` dependency
added). RED confirmed first (`ModuleNotFoundError` for the not-yet-created
module), then GREEN after implementation. Full suite: 206 passed, 3
skipped (same 3 pre-existing real-model `skipif` gates as before this
task — none of this task's tests are network-gated). `ruff check .` clean
repo-wide.

### Tasks 1–9 — panel, consensus, config/CLI wiring, jury meta-eval: design decisions, fix rounds, honest open items

Nine tasks (`docs/superpowers/plans/2026-08-09-multi-llm-jury.md`), built the
same subagent-driven way as Phase 1/2: an implementer sub-agent per task, then
a separate reviewer sub-agent against the task's spec before it was marked
complete (`.superpowers/sdd/2026-08-09-multi-llm-jury/progress.md` is the
ledger). This entry records the sub-project as a whole; Task 4's own detailed
entry above stands alongside it for the one task that wrote its own section.

#### Design decisions

- **Default-path-unchanged, not "one code path."** The design spec described
  the eventual shape as a 1-judge Claude panel being the only code path. The
  plan's self-review flagged this refinement explicitly and the implementation
  follows the refinement, not the original framing: `cli.py::run_verify` keeps
  the v1 single-judge branch **byte-identical and untouched**, and only takes
  the jury branch (`_build_judge_set` + `build_panel` + `panel.run_panel`) when
  `--judges` and/or `--judge` is actually given (`jury_requested`). This is
  strictly safer — every pre-existing v1 test stays green with no risk of the
  panel abstraction subtly changing v1 behavior, and there is no `asyncio.run`
  nested inside pydantic-evals' sync evaluator. Equivalence between a 1-judge
  panel and the v1 path is proven separately by
  `tests/test_panel.py::test_single_real_client_panel_matches_v1_judge_field`
  rather than by sharing one code path.
- **pydantic-ai OpenAI class: `OpenAIChatModel`, not `OpenAIModel`.** Verified
  before writing any code (Task 4 Step 0) by introspecting the installed
  `pydantic-ai` (2.27.x): `dir(pydantic_ai.models.openai)` has
  `OpenAIChatModel`/`OpenAIResponsesModel`, no `OpenAIModel`. `judge/client.py`'s
  `_model_ref` builds `OpenAIChatModel(spec.model, provider=OpenAIProvider(base_url=...,
  api_key=...))` accordingly — this is also what makes any `provider: openai`
  entry with a `base_url` (Ollama/vLLM/LM Studio) work, since `OpenAIProvider`
  just points the OpenAI-compatible client at a different endpoint. `openai>=1.0`
  was declared explicitly in `pyproject.toml` during Task 5 (previously arriving
  only transitively via `pydantic-ai`'s bundled extra).
- **Empty-tally → flagged pass, never a fabricated verdict.** `judge/consensus.py`'s
  four policies all route through `_voters()`, which counts only `status ==
  "voted"` votes. If a unit has zero voters (every judge abstained/errored/was
  not_applicable), `_empty()` returns `verdict="pass"` at `confidence=0.0` with a
  rationale that says no judge voted, and `agreement=None` — a deliberately
  *flagged* pass (visibly low-confidence, explicitly explained), never a silent
  or invented verdict of any other kind.
- **Unavailable judge → omitted at build, not at call time.** `judge/config.py`'s
  `_resolve_availability` marks a `JudgeSpec.available=False` when it has no
  resolvable API key and no `base_url`; `judge/panel.py::build_panel` then
  filters to `[s for s in specs if s.available]` before constructing any
  `JudgeClient`, so an unavailable judge never gets an agent built for it at
  all. If that filter empties the client list, `build_panel` returns `None` and
  `cli.py::run_verify` degrades to the same deterministic-only,
  `llm_skipped=True` outcome as the v1 no-key path — not a jury of zero judges,
  not a crash.

#### Fix rounds (evidence the review gate worked)

Of 9 tasks, **5 required a fix round** before being marked complete (T2, T4,
T5, T8, T9); **4 passed review clean on the first pass** (T1, T3, T6, T7).

- **T2 (consensus policies):** fix round fixed a `ruff` E501 line-length
  violation; no logic defect found.
- **T4 (JudgeClient):** fix round tightened error isolation, added a
  field-parity test, and corrected this log's own earlier overstatement that
  the `openai` dependency was a "latent risk" (it's `pydantic-ai`'s own pinned,
  bundled extra — see above).
- **T5 (judges.yaml loader + `--judge` mini-syntax):** fix round removed a raw
  secret echo from a `JudgeConfigError` message and added a missing-file
  path that previously surfaced an unguarded `OSError` instead of
  `JudgeConfigError`.
- **T8 (CLI wiring):** fix round made the bad-`--consensus` test offline-safe
  (it needed the guidelines fetch stubbed to avoid a real network call).
- **T9 (jury meta-eval):** the implementer caught **two provably-wrong test
  assertions baked into the plan itself** before writing any code against them
  — a `fleiss_kappa` chance-agreement input that doesn't actually evaluate to
  0.0, and a content-independent fake judge that would have wrongly asserted
  `1.0` accuracy for a fake that is truthfully only `0.5`-correct under the
  unchanged `meta_eval` scoring rule. The controller resolved both by
  correcting the plan's test snippets (not by weakening the assertions), then a
  fix round added `_require_full_denominator` to guard the real-model path's
  per-judge accuracy against a silent case-count shrink (mirrors Fix round 1's
  denominator guard in the Task 13 section above).

#### Honest open items — pre-registered before any real-model run

**Pre-registered hypothesis** (verbatim from `evals/jury_eval.py`'s module
docstring, written before any live-model jury run): *an ensemble (jury) of
independent LLM judges achieves HIGHER golden-set per-case accuracy than the
single best individual judge.* A null (zero) or NEGATIVE lift is explicitly
called out as a valid, fully expected-possible outcome that must be reported
unchanged — never massaged, clamped, or hidden; there is no code path that
floors `lift` at zero.

**The three headline metrics — measured against live models 2026-08-09 (actuals below); each also validated offline first for aggregation-logic correctness:**

- **Real per-judge accuracy** over the 44-case golden set, per configured
  judge (`evals/jury_eval.py::run(specs=...)` → `meta_eval.run` per judge).
- **Inter-judge agreement** — Fleiss' κ per rubric dimension over real judges'
  flagged/not-flagged decisions (`fleiss_kappa`, `_inter_judge_kappa`).
- **Jury-vs-single-judge lift** per consensus policy (`jury_accuracy[policy] -
  best_single_accuracy`).

All three require API keys for at least two configured judges; a key was provided
on 2026-08-09 and produced the **Real-model actuals** recorded below.
Independently, the *aggregation logic* was validated offline first against
synthetic/fake judge clients: `collect_grid`, all four consensus policies,
`fleiss_kappa`'s arithmetic, and the denominator guard are exercised by
`tests/test_jury_eval.py` and pass (`uv run pytest tests/test_jury_eval.py -v`) —
proving the scoring machinery correct independently of any live run.

**Real-model actuals — 2026-08-09 (measured, grounding-free, 44-case golden set).**
A live 3-judge Claude panel — **haiku-4.5, sonnet-5, opus-4.8** (all via
`ANTHROPIC_API_KEY`) — was run over the full golden set through a rate-limited
harness with an all-cells-voted integrity gate: **all 1,056 grid cells returned a
real verdict (0 errored)**, so every number below is over the complete,
un-shrunken set. (An earlier 2026-08-09 attempt was truncated by API-credit
exhaustion at ~700/1,056 cells and reported NO numbers; this run replaces it.)

Per-judge per-case accuracy: **haiku 95.5% (42/44) · opus 95.5% (42/44) · sonnet
81.8% (36/44)**. Best single judge = 42/44.

Jury accuracy by consensus policy, and lift vs the best single judge:

| policy | accuracy | lift vs best single |
|---|---|---|
| `unanimous` | **100% (44/44)** | **+4.5% (+2 cases)** |
| `majority_severe` (default) | 95.5% (42/44) | 0.0 |
| `confidence_weighted` \* | 95.5% (42/44) | 0.0 |
| `most_severe` | 79.5% (35/44) | −15.9% (−7 cases) |

Inter-judge agreement (Fleiss' κ, flagged/not-flagged, per dimension): high on
objective categories — third-party-trademark **0.91**, price-in-description
**0.84**, unauthorized-contact-links **0.84**, beta/demo **0.83**,
other-platform-mentions **0.80** — and lower on subjective ones —
misleading-claims **0.42**, keyword-stuffing **0.43**, placeholder-text **0.22**.

**Honest read of the pre-registered hypothesis** ("an ensemble beats the best
single judge"): **partially supported.** Only the precision-favoring `unanimous`
policy beats the best single judge, and only by 2 cases (100% vs 95.5%); the
recall-favoring `most_severe` is markedly worse (−7 cases — its lone-judge false
positives on clean controls dominate); `majority_severe` and `confidence_weighted`
merely tie. On this set the ensemble's value is **precision**: all three judges
already had near-perfect recall on the planted violations and differed mainly in
false positives on clean controls, so requiring unanimity to flag suppresses those
idiosyncratic single-judge errors. N is small (44 cases) — a 2-case swing is
indicative, not decisive.

\* `confidence_weighted` is **degenerate** on this offline-scored path: the
collected grid retains only the verdict string, so all confidences are equal and
the policy reduces to a summed-count majority (hence it equals `majority_severe`
here). A faithful confidence-weighted figure needs the real per-vote confidences
retained end-to-end — recorded as future work, not reported as a distinct result.

Method notes: grounding-free (no live guideline citations), matching the
pre-registered meta-eval methodology; the golden set is 44 realistic *synthetic*
cases grounded in the 8 rubric dimensions + Apple §2.3/5.2 (see `evals/dataset.py`),
so these figures characterize judge behavior on that curated set, not production
App Store traffic. The shipped `collect_grid` fans out all ~1k calls at once
(no concurrency cap — safe only for the instant offline fakes); this run used a
bounded-concurrency runner with retry + the integrity gate.

### Task 10 — Documentation (this entry + README)

README gained a "Multi-LLM jury (optional)" section: what the jury is, the
`judges.yaml` schema (env-var-reference secrets only, `judges.example.yaml`
reproduced verbatim), the four `--consensus` policies, `--judge`/
`--max-concurrency`, the self-hosted (`base_url`) note, and the same honest
status line as above — no accuracy/κ/lift numbers, because none have been
measured against real models. Full suite: `uv run pytest -q` → **238 passed, 3
skipped** (the 3 skips are the pre-existing `ANTHROPIC_API_KEY`-gated
real-model tests, unrelated to the jury docs change). `uv run ruff check .` →
**All checks passed!**

## Persistence (sub-project B)

Ten tasks (`docs/superpowers/plans/2026-08-10-persistence.md`), built the same
subagent-driven way as the jury sub-project: an implementer sub-agent per
task, then a separate reviewer sub-agent against the task's spec before it
was marked complete (`.superpowers/sdd/2026-08-10-persistence/progress.md` is
the ledger).

### Design decisions

- **Opt-in, zero-new-dependency default.** Persistence activates only when
  `--db` is given. `SqliteRepository` (the only shipped `Repository`) uses
  the standard library's `sqlite3` — no ORM, no new runtime dependency for
  the default path. With no `--db`, `verify` is byte-for-byte the same
  command it was before this sub-project: same output, same offline-by-default
  behavior, same dependency set.
- **Prompt-based verdict-cache key, `PROMPT_VERSION` = a hash of the system
  prompt.** `persistence/cache.py::verdict_cache_key(prompt, model_name)`
  hashes `(PROMPT_VERSION, model_name, prompt)`, where `PROMPT_VERSION` is a
  sha256 of `judge/prompts.py::TEXT_SYSTEM_PROMPT`. The full built prompt
  already encodes the rubric dimension, every locale text field, and the
  grounding text actually used, so the key needs no separate fields for
  those; folding the system prompt in as `PROMPT_VERSION` means an edit to
  the judge's own instructions invalidates every cached verdict
  automatically, rather than silently serving stale reasoning under a new
  prompt. A cache hit is therefore, by construction, never anything other
  than the literal, identical prior computation.
- **`DefaultCommandGroup` (a `TyperGroup` subclass) for CLI backward
  compatibility.** Adding `history`/`diff`/`similar` as real subcommands
  alongside `verify` would normally force every invocation to name a
  subcommand, once typer has more than one `@app.command()`. `cli.py`'s
  `DefaultCommandGroup` overrides `parse_args`/`resolve_command` to prepend
  `verify` whenever the first token isn't a known subcommand name, so
  `asc-verify <path>` keeps working exactly as before. Task 7's report
  documents that the brief's literal `class DefaultCommandGroup(click.Group)`
  does not compose with the installed typer (0.27.1) — it never builds a
  `click.Group` at all, `TyperGroup` reimplements group dispatch directly on
  `click.Command` — so the implementer verified `TyperGroup` empirically
  (reading its source, then a throwaway 3-command probe app) before wiring
  the real subclass into `cli.py`.
- **Report-first-then-save.** In `verify()`, the report is rendered to
  stdout and the exit code is fully decided from `report` *before* the
  persistence block runs. The whole `_persist_run(...)` call is wrapped in a
  bare `except Exception`, which converts any persistence failure — a broken
  DB, a locked file, anything else — into a `WARNING:` on stderr, never a
  change to the exit code and never a reason to hide the already-printed
  gate result.
- **Semantic recall: bring-your-own embedder, no bundled model.**
  `persistence/semantic.py` ships `Embedder`/`SemanticIndex` protocols, a
  fully offline `StubEmbedder`/`InMemoryIndex` pair for tests and local dev,
  and `ChromaIndex` (backed by the optional `chromadb` extra). `chromadb` is
  imported lazily inside `ChromaIndex.__init__`, never at module top level,
  so importing `persistence.semantic` — and everything that transitively
  imports it, including the default no-extra CLI install — never pays that
  cost. `ChromaIndex` always takes an injected `Embedder` and passes vectors
  to chromadb explicitly (`embeddings=`/`query_embeddings=`), so it never
  falls back to chromadb's own default embedding function; this codebase
  deliberately ships no real embedding model of its own, only the protocol
  and the offline stub.

### Fix rounds

Of 10 tasks, **2 required a fix round** (T2, T7); 8 passed review clean on
the first pass.

- **T2 (verdict-cache keys):** the first pass shipped `verdict_cache_key`
  correctly reading `PROMPT_VERSION` from module scope, but no test actually
  asserted the key changes when `PROMPT_VERSION` does — a regression that
  dropped `PROMPT_VERSION` from the key would have gone undetected and
  silently served stale-prompt verdicts as cache hits. Fix round added
  `test_key_depends_on_prompt_version` (monkeypatches `PROMPT_VERSION` and
  asserts the key changes), `e09eba3`.
- **T7 (CLI wiring):** two Important findings. (1) An `Edit`-tool anchor
  mistake during the original implementation orphaned a regression-guard
  assertion (`assert "WARNING" not in result.output`) onto the wrong test,
  silently gutting `test_healthy_jury_run_has_no_degraded_warning`'s only
  WARNING-absence check — restored to the correct test. (2) More
  substantively, `run_verify`'s return contract had stayed the pre-existing
  `(report, llm_skipped)` 2-tuple, so `_persist_run` never had access to the
  ingested `AppMetadata` or the `Guidelines` actually used: every persisted
  `RunRecord.app_id`/`.primary_locale` came out `None` (making
  `history --app-id` filtering inert), and `_persist_run` worked around the
  missing `Guidelines` by re-fetching guidelines a second time — a real
  double network fetch, and a risk that the persisted snapshot could
  mismatch what the verdicts were actually graded against. The fix widened
  `run_verify`'s return to a `VerifyOutcome` NamedTuple (`report,
  llm_skipped, meta, guidelines`), threading the already-computed
  `meta`/`guidelines` out instead of discarding or re-fetching them — so
  `app_id`/`primary_locale` persist for real and the guideline snapshot can
  never mismatch the graded verdicts. Commit `e82234e`.

### Honest open items

- **`ChromaIndex` + a real embedder is not exercised in CI (or in this dev
  environment).** `chromadb` lives behind the optional `semantic` extra;
  neither CI nor the environment this branch was built in has it installed.
  `tests/test_semantic.py::test_chroma_index_gated_behind_dependency` uses
  `pytest.importorskip("chromadb")` and skips cleanly rather than running —
  confirmed directly: `uv run pytest -rs` reports
  `SKIPPED [1] tests/test_semantic.py:23: could not import 'chromadb'`. Only
  `StubEmbedder`/`InMemoryIndex` (a deterministic bag-of-tokens embedder with
  no notion of meaning) are genuinely exercised; the real chromadb add/query
  API surface has never actually run against a real embedding model.
- **`RunRecord.version` is always `None`.** `AppMetadata` has no `version`
  field today, so there is nothing for `run_verify`/`_persist_run` to
  populate it from. The field and the sqlite column exist (for a future
  ASC-API-sourced adapter that does carry a version), but every run
  persisted by this codebase today has `version=None`.
- **Jury-path caching is deferred.** `--cache` is threaded only into
  `judge_field`'s single-judge text path — `run_verify`'s `cache` kwarg is
  only ever applied on the non-jury branch. A `--judges`/`--judge` jury run
  never reads or writes the verdict cache, regardless of `--cache`.

### Task 10 — Documentation (this entry + README)

README gained a "Persistence (optional)" section: the opt-in `--db` flag
(URL or bare path), `--cache`/`--no-cache`, `--no-save`, `history` and
`diff`, the repository-pattern note, the verdict-cache key description, and
semantic recall's bring-your-own-embedder status — plus the same
"Honest status" callout pattern used by the jury section above. The
`Development` section's stale test count (`183 passed, 3 skipped`, left over
from Phase 1) was corrected to the real current numbers while this file was
already being touched for accuracy. Full suite: `uv run pytest -q` →
**282 passed, 4 skipped** (3 are the pre-existing `ANTHROPIC_API_KEY`-gated
real-model tests; 1 is `test_chroma_index_gated_behind_dependency`, skipped
because `chromadb` isn't installed in this environment either — the same
condition CI runs under). `uv run ruff check .` → **All checks passed!**

## Code analyzer (sub-project C)

Third of five v2 sub-projects. Spec + plan pre-registered
(`docs/superpowers/specs/2026-08-10-code-analyzer-design.md`,
`docs/superpowers/plans/2026-08-10-code-analyzer.md`) before any feature code.
Built inline (the 200-subagent session cap was reached before Task 1, so the
subagent-driven method fell back to controller-run inline TDD per the user's
call — same test-first discipline and per-task commits, but no independent
reviewer gate this session; the whole-branch self-review stands in).

### What shipped

A new `asc-verify code <project-path>` command running **deep AST-level static
analysis** over a local Apple app project (Swift/Obj-C sources + `Info.plist` +
`*.entitlements` + `PrivacyInfo.xcprivacy`), plus `verify --code <path>` which
folds code findings into the unified PASS/WARN/BLOCK gate. Architecture:
`code/project.py` (offline loader) → pluggable `SourceParser` (`code/parser.py`)
→ a `Rule` REGISTRY (`code/rules/`) → `code/analyzer.py`, with an opt-in
`code/jury.py` LLM layer.

- **Parser strategy.** tree-sitter is the default offline backend
  (`tree-sitter` + `tree-sitter-language-pack`, behind the `[code]` extra,
  lazy-imported). Node types were **empirically verified** against
  tree-sitter-language-pack 1.14.3 before coding the queries (swift identifiers
  are `simple_identifier`; obj-c uses `identifier`/`type_identifier`; string
  *content* lives in `line_str_text`/`string_content` children — read directly
  so obj-c `@"..."` yields a clean value, not a `@"`-prefixed one). The optional
  SwiftSyntax backend is a **BYO subprocess helper** (no importable pip package
  exists), with a tested unavailable→tree-sitter fallback that never fabricates.
- **Curated 10-rule catalog**, each mapped to a guideline section, each finding
  anchored to `file:line` + evidence: privacy/tracking (5.1.x — idfa-without-att,
  missing-usage-string, required-reason-api-undeclared, boilerplate-usage-string),
  deprecated/private API (2.5.x — uiwebview-usage, private-api-symbol), security
  (2.5.2 — ats-arbitrary-loads, insecure-http-endpoint), compliance
  (encryption-export-undeclared, canopenurl-undeclared-scheme). The
  cross-artifact rules (code symbol × manifest) are the AST win over regex.
- **Opt-in jury** (`--jury`) reuses the metadata jury's `JudgeSpec` config,
  consensus `POLICIES`, and `JudgeVote`/`PanelVerdict` models with code-specific
  units; adjudicates interpretive findings and answers a fixed question set
  (5.1.1(v) account-gating, 3.1.1 IAP-bypass). Off by default; error-isolated;
  jury items tagged `source="jury"` with the full vote record.

### Honesty invariants held

- **Additive / offline by default.** With no `code` command and no `--code`,
  `verify` is byte-unchanged and pulls zero new *core* deps (tree-sitter is
  behind `[code]`). `code` with no `--jury` makes zero network calls.
- **Never fabricate.** Missing manifest, unavailable parser backend, or absent
  toolchain each produce a factual state; every finding points at real
  `file:line` + evidence. Jury-sourced items are never presented as static fact.
- **Curated, not exhaustive.** The rule catalog and the private-API /
  required-reason denylists are documented as non-exhaustive with expected
  false negatives — the analysis ceiling is AST-structural, not type inference
  or data-flow, and the tool never claims otherwise.

### Honest open items

- The SwiftSyntax backend is exercised in tests only via a **fake helper**; no
  real Swift toolchain runs in CI. The unavailable→tree-sitter fallback IS
  directly tested. Nobody has run the backend against a real SwiftSyntax helper.
- The `private-api-symbol` and `required-reason-api-undeclared` lists are curated
  high-signal subsets, not Apple's full sets. `symbols()` is presence-based:
  aliased/dynamically-constructed calls (`NSClassFromString`, KVC) are not
  detected.
- Symbol-presence findings report `line=1` (first-occurrence line resolution is
  not yet threaded through `symbols()`); string/config findings carry real lines.
- Persisting `code` runs via the repository (sub-project B) is not wired;
  `CodeReport` is serializable, so it slots in later. The jury path is not cached.

### Verification

Built task-by-task (TDD, 11 tasks) on `feat/code-analyzer`. Full suite with the
`[code]` extra: `uv run pytest -q` → **331 passed, 4 skipped** (3 real-model
`ANTHROPIC_API_KEY`-gated, 1 ChromaIndex gated behind `semantic`).
`uv run ruff check .` → **All checks passed!** A live end-to-end run over a
synthetic flawed project surfaced 6 findings across 5 categories with correct
`file:line`/evidence and a BLOCK gate (real exit code 1; clean project exit 0).
