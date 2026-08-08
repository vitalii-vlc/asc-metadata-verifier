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
