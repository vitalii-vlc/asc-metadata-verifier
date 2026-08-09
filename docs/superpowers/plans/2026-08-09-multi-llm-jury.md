# Multi-LLM Jury Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in panel ("jury") of independently-configured LLM judges (Claude + any OpenAI-compatible endpoint, incl. self-hosted) that run concurrently, vote per (locale, dimension) and per screenshot, and collapse to one gate verdict via a selectable consensus policy — recording every raw vote so inter-judge agreement and jury-vs-single accuracy become measurable.

**Architecture:** A `JudgePanel` of `JudgeClient`s runs async under a shared semaphore; a pluggable `ConsensusPolicy` aggregates each unit's `JudgeVote`s into the same `RubricVerdict` the gate already consumes, plus a `PanelVerdict` preserving the raw votes. The jury path activates **only** when `--judges`/`--judge` is given; the no-jury default runs v1's existing `judge_field`/`judge_screenshots` code **unchanged** (so every v1 test stays green and there is no nested event loop inside pydantic-evals' sync evaluator). A 1-judge panel is proven equal to v1 at the panel level.

**Tech Stack:** Python 3.11 (uv) · pydantic-ai (multi-provider judges, structured output) · pydantic v2 · pydantic-evals · logfire · pyyaml · typer + rich · asyncio. No new hard dependency except the `openai` extra for pydantic-ai's OpenAI-compatible models (Task 4 confirms/adds it).

## Global Constraints

- **Honesty bar (hard):** never fabricate a finding, a `guideline_ref`, or a vote. A judge that abstains, errors, is unavailable, or cannot see an input is recorded as such and **excluded from the tally** — never counted as agreeing. Agreement/accuracy numbers come from real runs, never asserted.
- **Backward compatible:** with no `--judges`/`--judge`, the CLI runs the v1 code path unchanged; `report.verdicts` and every existing test are unaffected. The jury is purely additive.
- **Secrets by reference only:** `judges.yaml` names env vars (`api_key_env: OPENAI_API_KEY`); it never holds a raw key. `judges.example.yaml` (committed) contains no secrets.
- **Offline-safe / CI-green without keys:** consensus, config, client, and panel are fully testable with injected `FunctionModel`/`TestModel` and monkeypatched env. Real-model behavior lives behind key-gated tests (`@pytest.mark.skipif(not os.environ.get(...))`).
- **Determinism first:** the panel only runs where v1 already spent an LLM call; deterministic checks are untouched and never juried.
- **Consensus policy names (exact, 4):** `majority_severe` (default), `most_severe`, `unanimous`, `confidence_weighted`.
- **Verdict/severity ordering:** verdict `fail`(2) > `warn`(1) > `pass`(0); severity `high`(2) > `medium`(1) > `low`(0).
- **Style:** ruff (`E,F,I,UP,B`), line-length 100, target py311. Match v1 module/docstring conventions. Tests are offline `FunctionModel`-driven; async panel code is driven from sync tests via `asyncio.run(...)` (no `pytest-asyncio` dependency).
- **Every task ends green:** `uv run pytest` all pass, `uv run ruff check .` clean, then commit.

---

## File Structure

**New modules**
- `src/asc_metadata_verifier/judge/prompts.py` — shared text+vision prompt/grounding builders + system prompts (moved verbatim from `agent.py`/`vision.py`).
- `src/asc_metadata_verifier/judge/images.py` — `IMAGE_SIGNATURES` + `read_image()` (moved from `vision.py`).
- `src/asc_metadata_verifier/judge/consensus.py` — `ConsensusPolicy` + 4 policies + `POLICIES` registry + `DEFAULT_POLICY`.
- `src/asc_metadata_verifier/judge/client.py` — `JudgeClient` (async `run_text`/`run_vision`, `from_spec`/`from_model`, error/not-applicable handling).
- `src/asc_metadata_verifier/judge/config.py` — `JudgeSpec`, `JudgeSet`, `load_judges`, `judges_from_cli`, `merge_specs`, `JudgeConfigError`.
- `src/asc_metadata_verifier/judge/panel.py` — `JudgePanel` (async `judge_text`/`judge_vision`, sync `run_panel`) + `build_panel`.
- `src/asc_metadata_verifier/evals/jury_eval.py` — per-judge accuracy, inter-judge Fleiss' κ, jury-vs-single lift.
- `judges.example.yaml` (repo root) — committed template, env-var refs only.
- Tests: `tests/test_consensus.py`, `tests/test_client.py`, `tests/test_config.py`, `tests/test_panel.py`, `tests/test_jury_eval.py`, plus additions to `tests/test_models.py`, `tests/test_gate.py`, `tests/test_report.py`, `tests/test_cli.py`.

**Changed modules**
- `models.py` — `+JudgeVote`, `+PanelVerdict`, `GateReport.panels`.
- `judge/agent.py`, `judge/vision.py` — import builders from `prompts.py`/`images.py` (pure refactor; behavior identical).
- `gate.py` — `evaluate(..., panels=None)` passthrough.
- `report.py` — optional panel-disagreement section.
- `cli.py` — `--judges`, `--judge`, `--consensus`, `--max-concurrency`; jury branch; `JudgeConfigError` handling.
- `README.md`, `BUILD_LOG.md` — jury usage + honest build record.

---

## Task 1: Data model — JudgeVote, PanelVerdict, GateReport.panels

**Files:**
- Modify: `src/asc_metadata_verifier/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: existing `RubricVerdict`, `GateReport`.
- Produces: `JudgeStatus` (Literal), `JudgeVote`, `PanelVerdict`; `GateReport.panels: list[PanelVerdict]`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_models.py`:

```python
from asc_metadata_verifier.models import GateReport, JudgeVote, PanelVerdict, RubricVerdict


def _rv(verdict="fail", severity="high", confidence=0.9, field="description"):
    return RubricVerdict(
        dimension="placeholder_text", verdict=verdict, severity=severity,
        confidence=confidence, rationale="r", locale="en-US", field=field,
    )


def test_judge_vote_voted_carries_verdict():
    v = JudgeVote(judge="claude", status="voted", verdict=_rv(), latency_ms=12.0)
    assert v.status == "voted"
    assert v.verdict.verdict == "fail"


def test_judge_vote_error_and_defaults():
    v = JudgeVote(judge="local", status="error", error="boom")
    assert v.verdict is None and v.error == "boom" and v.latency_ms is None


def test_panel_verdict_roundtrips_and_holds_votes():
    p = PanelVerdict(
        locale="en-US", dimension="placeholder_text", field="description",
        votes=[JudgeVote(judge="a", status="voted", verdict=_rv()),
               JudgeVote(judge="b", status="not_applicable")],
        consensus=_rv(), policy="majority_severe", agreement=0.5,
    )
    again = PanelVerdict.model_validate_json(p.model_dump_json())
    assert again.consensus.verdict == "fail"
    assert [x.status for x in again.votes] == ["voted", "not_applicable"]


def test_gate_report_panels_defaults_empty_and_is_additive():
    r = GateReport(status="PASS", guidelines_available=True)
    assert r.panels == []
    r2 = GateReport(status="BLOCK", guidelines_available=True,
                    verdicts=[_rv()], panels=[])
    assert GateReport.model_validate_json(r2.model_dump_json()).status == "BLOCK"
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_models.py -q` → FAIL (ImportError: JudgeVote/PanelVerdict).

- [ ] **Step 3: Implement** — add to `models.py` (after `RubricVerdict`, before `GateReport`; keep `from typing import Literal`):

```python
JudgeStatus = Literal["voted", "abstained", "error", "not_applicable"]


class JudgeVote(BaseModel):
    """One judge's outcome for one unit. `verdict` is set iff status == 'voted';
    `error` iff status == 'error'. abstained/error/not_applicable are excluded
    from the consensus tally but retained for the honesty record."""

    judge: str
    status: JudgeStatus
    verdict: RubricVerdict | None = None
    error: str | None = None
    latency_ms: float | None = None


class PanelVerdict(BaseModel):
    """Every judge's vote on one (locale, dimension) [text] or (screenshot,
    dimension) [vision] unit, plus the aggregated consensus the gate consumes.
    `field` is descriptive (copied from the consensus), not a grouping key —
    units are keyed by (locale, dimension)."""

    locale: str
    dimension: str
    field: str
    votes: list[JudgeVote]
    consensus: RubricVerdict
    policy: str
    agreement: float | None = None
```

Add to `GateReport`:

```python
    panels: list[PanelVerdict] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_models.py -q` → PASS. Then `uv run ruff check src/asc_metadata_verifier/models.py`.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(jury): JudgeVote, PanelVerdict, GateReport.panels"`

---

## Task 2: Consensus policies

**Files:**
- Create: `src/asc_metadata_verifier/judge/consensus.py`
- Test: `tests/test_consensus.py`

**Interfaces:**
- Consumes: `JudgeVote`, `RubricVerdict`.
- Produces: `POLICIES: dict[str, ConsensusPolicy]`, `DEFAULT_POLICY = "majority_severe"`. Each policy: `policy(votes: list[JudgeVote], *, locale: str, dimension: str, default_field: str) -> tuple[RubricVerdict, float | None]`. Only `status == "voted"` votes count; on an empty voter set returns a flagged `pass`/`low`/`confidence=0.0` verdict and `agreement=None`. The aggregated verdict copies `field`/`offending_quote`/`rationale`/`guideline_ref`/`suggested_fix` from the highest-confidence voter matching the chosen verdict; `severity` = max matching detail-severity; `confidence` = mean matching confidence.

- [ ] **Step 1: Write failing tests** — `tests/test_consensus.py`:

```python
from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES
from asc_metadata_verifier.models import JudgeVote, RubricVerdict


def _vote(judge, verdict, severity="high", confidence=0.9, status="voted", field="description",
          quote="q", ref=None, fix="f", rationale="r"):
    rv = None
    if status == "voted":
        rv = RubricVerdict(dimension="d", verdict=verdict, severity=severity, confidence=confidence,
                           rationale=rationale, offending_quote=quote, guideline_ref=ref,
                           suggested_fix=fix, locale="x", field=field)
    return JudgeVote(judge=judge, status=status, verdict=rv)


def _run(name, votes):
    return POLICIES[name](votes, locale="en-US", dimension="placeholder_text", default_field="description")


def test_registry_has_exactly_the_four_named_policies():
    assert set(POLICIES) == {"majority_severe", "most_severe", "unanimous", "confidence_weighted"}
    assert DEFAULT_POLICY == "majority_severe"


def test_majority_plurality_wins():
    votes = [_vote("a", "fail"), _vote("b", "fail"), _vote("c", "pass")]
    cons, agr = _run("majority_severe", votes)
    assert cons.verdict == "fail" and abs(agr - 2 / 3) < 1e-9


def test_majority_tie_breaks_to_more_severe():
    votes = [_vote("a", "fail"), _vote("b", "warn")]
    cons, _ = _run("majority_severe", votes)
    assert cons.verdict == "fail"


def test_most_severe_takes_worst():
    votes = [_vote("a", "pass"), _vote("b", "warn"), _vote("c", "pass")]
    cons, _ = _run("most_severe", votes)
    assert cons.verdict == "warn"


def test_unanimous_requires_all_to_escalate():
    assert _run("unanimous", [_vote("a", "fail"), _vote("b", "fail")])[0].verdict == "fail"
    assert _run("unanimous", [_vote("a", "fail"), _vote("b", "warn")])[0].verdict == "warn"
    assert _run("unanimous", [_vote("a", "fail"), _vote("b", "pass")])[0].verdict == "pass"


def test_confidence_weighted_prefers_high_confidence_side():
    votes = [_vote("a", "fail", confidence=0.4), _vote("b", "pass", confidence=0.55),
             _vote("c", "pass", confidence=0.55)]
    assert _run("confidence_weighted", votes)[0].verdict == "pass"


def test_non_voters_excluded_from_tally_but_agreement_over_voters():
    votes = [_vote("a", "fail"), _vote("b", None, status="error"),
             _vote("c", None, status="not_applicable"), _vote("d", "fail")]
    cons, agr = _run("majority_severe", votes)
    assert cons.verdict == "fail" and agr == 1.0  # 2/2 voters agree


def test_empty_voter_set_is_flagged_pass_not_a_fabricated_fail():
    votes = [_vote("a", None, status="error"), _vote("b", None, status="abstained")]
    cons, agr = _run("most_severe", votes)
    assert cons.verdict == "pass" and cons.confidence == 0.0 and agr is None
    assert "no judge" in cons.rationale.lower()


def test_representative_fields_come_from_highest_confidence_matching_voter():
    votes = [_vote("a", "fail", confidence=0.6, quote="low-conf", fix="fix-a"),
             _vote("b", "fail", confidence=0.95, quote="high-conf", fix="fix-b"),
             _vote("c", "pass", confidence=0.99, quote="ignore")]
    cons, _ = _run("majority_severe", votes)
    assert cons.offending_quote == "high-conf" and cons.suggested_fix == "fix-b"


def test_severity_is_max_and_confidence_is_mean_among_matching():
    votes = [_vote("a", "fail", severity="medium", confidence=0.8),
             _vote("b", "fail", severity="high", confidence=0.6)]
    cons, _ = _run("majority_severe", votes)
    assert cons.severity == "high" and abs(cons.confidence - 0.7) < 1e-9


def test_single_voter_consensus_equals_that_voter_verbatim():
    v = _vote("only", "warn", severity="medium", confidence=0.77, quote="qq", fix="ff")
    cons, agr = _run("majority_severe", [v])
    assert (cons.verdict, cons.severity, cons.confidence) == ("warn", "medium", 0.77)
    assert cons.offending_quote == "qq" and cons.suggested_fix == "ff" and agr == 1.0
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_consensus.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** — `src/asc_metadata_verifier/judge/consensus.py`:

```python
"""Consensus policies: collapse a panel's per-judge votes into one verdict.

Only `status == "voted"` votes count toward the tally; abstained/error/
not_applicable votes are excluded (but retained by the caller in
`PanelVerdict.votes`). Never fabricate a verdict: an empty voter set yields a
flagged `pass` (confidence 0.0) whose rationale says no judge voted, and
`agreement=None`. The aggregated verdict's descriptive fields come from the
highest-confidence voter that matches the chosen verdict, so the quote can
never contradict the verdict.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Callable

from asc_metadata_verifier.models import JudgeVote, RubricVerdict

ConsensusPolicy = Callable[..., "tuple[RubricVerdict, float | None]"]

_VERDICT_RANK = {"pass": 0, "warn": 1, "fail": 2}
_RANK_VERDICT = {0: "pass", 1: "warn", 2: "fail"}
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


def _voters(votes: list[JudgeVote]) -> list[RubricVerdict]:
    return [v.verdict for v in votes if v.status == "voted" and v.verdict is not None]


def _empty(locale: str, dimension: str, field: str) -> tuple[RubricVerdict, None]:
    return (
        RubricVerdict(
            dimension=dimension, verdict="pass", severity="low", confidence=0.0,
            rationale="No judge produced a verdict for this unit.",
            locale=locale, field=field,
        ),
        None,
    )


def _assemble(chosen: str, voters: list[RubricVerdict], locale: str, dimension: str):
    matching = [rv for rv in voters if rv.verdict == chosen]
    rep = max(matching, key=lambda rv: rv.confidence)
    severity = max((rv.severity for rv in matching), key=lambda s: _SEVERITY_RANK[s])
    confidence = sum(rv.confidence for rv in matching) / len(matching)
    agreement = sum(1 for rv in voters if rv.verdict == chosen) / len(voters)
    return (
        RubricVerdict(
            dimension=dimension, locale=locale, field=rep.field,
            verdict=chosen, severity=severity, confidence=confidence,
            rationale=rep.rationale, offending_quote=rep.offending_quote,
            guideline_ref=rep.guideline_ref, suggested_fix=rep.suggested_fix,
        ),
        agreement,
    )


def _severe_tiebreak(tied: list[str]) -> str:
    return max(tied, key=lambda vd: _VERDICT_RANK[vd])


def majority_severe(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    tally = Counter(rv.verdict for rv in voters)
    top = max(tally.values())
    chosen = _severe_tiebreak([vd for vd, c in tally.items() if c == top])
    return _assemble(chosen, voters, locale, dimension)


def most_severe(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    chosen = _RANK_VERDICT[max(_VERDICT_RANK[rv.verdict] for rv in voters)]
    return _assemble(chosen, voters, locale, dimension)


def unanimous(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    chosen = _RANK_VERDICT[min(_VERDICT_RANK[rv.verdict] for rv in voters)]
    return _assemble(chosen, voters, locale, dimension)


def confidence_weighted(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    weights: dict[str, float] = defaultdict(float)
    for rv in voters:
        weights[rv.verdict] += rv.confidence
    top = max(weights.values())
    chosen = _severe_tiebreak([vd for vd, w in weights.items() if w == top])
    return _assemble(chosen, voters, locale, dimension)


DEFAULT_POLICY = "majority_severe"
POLICIES: dict[str, ConsensusPolicy] = {
    "majority_severe": majority_severe,
    "most_severe": most_severe,
    "unanimous": unanimous,
    "confidence_weighted": confidence_weighted,
}
```

- [ ] **Step 4: Run tests + lint** — `uv run pytest tests/test_consensus.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/judge/consensus.py`.

- [ ] **Step 5: Commit** — `git commit -am "feat(jury): four selectable consensus policies + registry"`

---

## Task 3: Shared judge helpers (prompts + image reading) — pure refactor

**Files:**
- Create: `src/asc_metadata_verifier/judge/prompts.py`, `src/asc_metadata_verifier/judge/images.py`
- Modify: `src/asc_metadata_verifier/judge/agent.py`, `src/asc_metadata_verifier/judge/vision.py`
- Test: existing `tests/test_judge.py`, `tests/test_vision.py` must stay green; add `tests/test_prompts.py`.

**Interfaces (Produces):**
- `prompts.TEXT_SYSTEM_PROMPT`, `prompts.VISION_SYSTEM_PROMPT`, `prompts.TEXT_FIELDS`
- `prompts.format_fields(locale_meta) -> str`
- `prompts.grounding_for_text(guidelines, dimension) -> str`
- `prompts.build_text_prompt(dimension, locale_meta, grounding) -> str`
- `prompts.grounding_for_vision(guidelines, dimension) -> str`
- `prompts.build_vision_prompt(dimension, screenshot, grounding) -> str`
- `images.IMAGE_SIGNATURES`, `images.read_image(screenshot) -> tuple[bytes, str] | None`

This is a **behavior-preserving move**. Copy the bodies verbatim from `agent.py` (`SYSTEM_PROMPT`→`TEXT_SYSTEM_PROMPT`, `_TEXT_FIELDS`→`TEXT_FIELDS`, `_format_fields`→`format_fields`, `_grounding_for`→`grounding_for_text`, `_build_prompt`→`build_text_prompt`) and `vision.py` (`SYSTEM_PROMPT`→`VISION_SYSTEM_PROMPT`, `_grounding_for`→`grounding_for_vision`, `_build_prompt`→`build_vision_prompt`, `_IMAGE_SIGNATURES`→`images.IMAGE_SIGNATURES`, `_read_image`→`images.read_image`).

- [ ] **Step 1: Create `prompts.py`** with the six functions/constants above (bodies copied verbatim; keep `from __future__ import annotations` and the `RubricDimension`/`VisionDimension`/`LocaleMetadata`/`Screenshot`/`Guidelines` imports the bodies need).

- [ ] **Step 2: Create `images.py`** with `IMAGE_SIGNATURES` + `read_image` (verbatim from `vision._read_image`, keeping the `logging.warning` skip semantics and signature-derived media type).

- [ ] **Step 3: Repoint `agent.py`** — delete the moved defs; `from asc_metadata_verifier.judge import prompts`; in `build_judge` use `prompts.TEXT_SYSTEM_PROMPT`; in `judge_field` call `prompts.grounding_for_text` and `prompts.build_text_prompt`. Keep `SYSTEM_PROMPT = prompts.TEXT_SYSTEM_PROMPT` as a module alias so any external import still resolves. Behavior unchanged.

- [ ] **Step 4: Repoint `vision.py`** — delete the moved defs; import `prompts` + `images`; `build_vision_judge` uses `prompts.VISION_SYSTEM_PROMPT`; `judge_screenshots` uses `images.read_image`, `prompts.grounding_for_vision`, `prompts.build_vision_prompt`. Keep `SYSTEM_PROMPT = prompts.VISION_SYSTEM_PROMPT` alias.

- [ ] **Step 5: Add `tests/test_prompts.py`**:

```python
from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.models import LocaleMetadata


def test_text_prompt_includes_grounding_and_fields():
    g = Guidelines(available=True, text="2.3 body", sections={"2.3": "2.3 body"}, source="t")
    lm = LocaleMetadata(locale="en-US", description="Also on Android")
    grounding = prompts.grounding_for_text(g, DIMENSIONS[0])
    out = prompts.build_text_prompt(DIMENSIONS[0], lm, grounding)
    assert "Android" in out and "2.3 body" in out


def test_grounding_empty_when_unavailable():
    g = Guidelines(available=False, text="", sections={}, source="off")
    assert prompts.grounding_for_text(g, DIMENSIONS[0]) == ""
```

- [ ] **Step 6: Run the FULL suite** — `uv run pytest -q` → all pass (test_judge.py + test_vision.py prove the refactor preserved behavior). `uv run ruff check .`

- [ ] **Step 7: Commit** — `git commit -am "refactor(judge): extract shared prompt + image helpers (no behavior change)"`

---

## Task 4: JudgeClient — one model, async, honesty-preserving

**Files:**
- Create: `src/asc_metadata_verifier/judge/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `prompts`, `RubricDimension`, `VisionDimension`, `Screenshot`, `LocaleMetadata`, `Guidelines`, `JudgeVote`, `RubricVerdict`, and (Task 5) `JudgeSpec`.
- Produces:
  - `JudgeClient(name, text_agent, vision_agent=None, supports_vision=False)`
  - `JudgeClient.from_model(name, model, *, supports_vision=False)` — builds both agents from an injected model (offline tests).
  - `JudgeClient.from_spec(spec)` — builds agents from a resolved `JudgeSpec` (real providers; keyless-constructible via `defer_model_check=True`).
  - `async run_text(dimension, locale_meta, grounding) -> JudgeVote`
  - `async run_vision(screenshot, image_bytes, media_type, dimension, grounding) -> JudgeVote`
- **Honesty stamping (must match v1 exactly):** text — stamp `locale`, `dimension`; force `guideline_ref=None` when `grounding` is falsy; **do not** stamp `field` (the text model reports which field). Vision — stamp `locale`, `dimension`, `field="screenshot"`; force `guideline_ref=None` when grounding falsy.
- A non-vision client's `run_vision` returns `JudgeVote(status="not_applicable")` with **no** model call. Any exception in a run becomes `JudgeVote(status="error", error=<str(exc)[:300]>)` — it never raises.

> **Step 0 (provider API verification, do first):** confirm how the installed `pydantic_ai` constructs an OpenAI-compatible model. Run `uv run python -c "import pydantic_ai, importlib; m=importlib.import_module('pydantic_ai.models.openai'); print([n for n in dir(m) if 'Model' in n])"`. Use whatever class it exposes (`OpenAIModel` or `OpenAIChatModel`) with a provider carrying `base_url`/`api_key` (`from pydantic_ai.providers.openai import OpenAIProvider`). If the import raises `ModuleNotFoundError: openai`, add `"openai>=1.0"` to `[project].dependencies` in `pyproject.toml` and `uv sync`. Record the exact class used in `BUILD_LOG.md`.

- [ ] **Step 1: Write failing tests** — `tests/test_client.py` (uses the same `FunctionModel` helper style as `tests/test_judge.py`):

```python
import asyncio

from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.client import JudgeClient
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.judge.vision import VISION_DIMENSIONS
from asc_metadata_verifier.models import LocaleMetadata, RubricVerdict, Screenshot


def _user_text(messages):
    out = []
    for m in messages:
        for p in getattr(m, "parts", []):
            if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                out.append(p.content)
    return "\n".join(out)


def _model(factory):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        v = factory(_user_text(messages))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, v.model_dump())])
    return FunctionModel(fn)


def _rv(**kw):
    base = dict(dimension="echo", verdict="fail", severity="high", confidence=0.9,
               rationale="r", offending_quote="Android", guideline_ref="2.3.99",
               locale="echo", field="description")
    base.update(kw)
    return RubricVerdict(**base)


def test_run_text_votes_and_stamps_authoritatively():
    client = JudgeClient.from_model("c", _model(lambda t: _rv()), supports_vision=False)
    lm = LocaleMetadata(locale="en-US", description="Also on Android")
    g = Guidelines(available=True, text="2.3.10 body", sections={"2.3.10": "body"}, source="t")
    grounding = "2.3.10 body"
    vote = asyncio.run(client.run_text(DIMENSIONS[1], lm, grounding))
    assert vote.status == "voted"
    assert vote.verdict.locale == "en-US"                 # authoritative
    assert vote.verdict.dimension == "other_platform_mentions"
    assert vote.verdict.guideline_ref == "2.3.99"         # grounding present -> not scrubbed


def test_run_text_scrubs_guideline_ref_when_no_grounding():
    client = JudgeClient.from_model("c", _model(lambda t: _rv()))
    lm = LocaleMetadata(locale="en-US", description="x")
    vote = asyncio.run(client.run_text(DIMENSIONS[0], lm, ""))   # empty grounding
    assert vote.verdict.guideline_ref is None


def test_run_text_error_becomes_error_vote_not_raise():
    def boom(_t):
        raise RuntimeError("kaboom")
    client = JudgeClient.from_model("c", _model(boom))
    lm = LocaleMetadata(locale="en-US", description="x")
    vote = asyncio.run(client.run_text(DIMENSIONS[0], lm, "g"))
    assert vote.status == "error" and "kaboom" in vote.error and vote.verdict is None


def test_non_vision_client_run_vision_is_not_applicable_without_a_call():
    called = {"n": 0}
    def fn(_t):
        called["n"] += 1
        return _rv()
    client = JudgeClient.from_model("c", _model(fn), supports_vision=False)
    s = Screenshot(locale="en-US", path="x.png")
    vote = asyncio.run(client.run_vision(s, b"\x89PNG\r\n\x1a\n", "image/png", VISION_DIMENSIONS[0], "g"))
    assert vote.status == "not_applicable" and called["n"] == 0


def test_vision_client_stamps_field_screenshot():
    client = JudgeClient.from_model("c", _model(lambda t: _rv(field="wrong")), supports_vision=True)
    s = Screenshot(locale="de-DE", path="x.png")
    vote = asyncio.run(client.run_vision(s, b"\x89PNG\r\n\x1a\n", "image/png", VISION_DIMENSIONS[0], ""))
    assert vote.status == "voted"
    assert vote.verdict.field == "screenshot" and vote.verdict.locale == "de-DE"
    assert vote.verdict.guideline_ref is None            # empty grounding scrubbed


def test_from_model_default_is_keyless():
    JudgeClient.from_model("c", _model(lambda t: _rv()), supports_vision=True)  # must not raise
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_client.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** — `src/asc_metadata_verifier/judge/client.py`:

```python
"""One configured model, wrapped as a judge that votes on text and (optionally)
vision units. Mirrors v1's honesty post-processing per call and never raises
into the panel: any error becomes an `error` JudgeVote."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pydantic_ai import Agent, BinaryContent

from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.models import JudgeVote, RubricVerdict

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from asc_metadata_verifier.judge.config import JudgeSpec
    from asc_metadata_verifier.judge.rubric import RubricDimension
    from asc_metadata_verifier.judge.vision import VisionDimension
    from asc_metadata_verifier.models import LocaleMetadata, Screenshot

_ERR_MAX = 300


class JudgeClient:
    def __init__(self, name, text_agent, vision_agent=None, supports_vision=False):
        self.name = name
        self._text_agent = text_agent
        self._vision_agent = vision_agent
        self.supports_vision = supports_vision

    @classmethod
    def from_model(cls, name: str, model: "Model | str", *, supports_vision: bool = False):
        text = Agent(model, output_type=RubricVerdict, system_prompt=prompts.TEXT_SYSTEM_PROMPT)
        vision = (
            Agent(model, output_type=RubricVerdict, system_prompt=prompts.VISION_SYSTEM_PROMPT)
            if supports_vision else None
        )
        return cls(name, text, vision, supports_vision)

    @classmethod
    def from_spec(cls, spec: "JudgeSpec"):
        model_ref = _model_ref(spec)
        text = Agent(model_ref, output_type=RubricVerdict,
                     system_prompt=prompts.TEXT_SYSTEM_PROMPT, defer_model_check=True)
        vision = (
            Agent(model_ref, output_type=RubricVerdict,
                  system_prompt=prompts.VISION_SYSTEM_PROMPT, defer_model_check=True)
            if spec.vision else None
        )
        return cls(spec.name, text, vision, spec.vision)

    async def run_text(self, dimension: "RubricDimension", locale_meta: "LocaleMetadata",
                       grounding: str) -> JudgeVote:
        prompt = prompts.build_text_prompt(dimension, locale_meta, grounding)
        # text: field is model-reported (v1 behavior) -> stamp only locale+dimension
        return await self._run(self._text_agent, [prompt],
                               locale_meta.locale, dimension.id, None, grounding)

    async def run_vision(self, screenshot: "Screenshot", image_bytes: bytes, media_type: str,
                         dimension: "VisionDimension", grounding: str) -> JudgeVote:
        if not self.supports_vision or self._vision_agent is None:
            return JudgeVote(judge=self.name, status="not_applicable")
        prompt = prompts.build_vision_prompt(dimension, screenshot, grounding)
        content = [prompt, BinaryContent(data=image_bytes, media_type=media_type)]
        return await self._run(self._vision_agent, content,
                               screenshot.locale, dimension.id, "screenshot", grounding)

    async def _run(self, agent, content, locale, dimension, field, grounding) -> JudgeVote:
        start = time.monotonic()
        try:
            result = await agent.run(content)
        except Exception as exc:  # noqa: BLE001 - one judge's failure must not kill the panel
            return JudgeVote(judge=self.name, status="error", error=str(exc)[:_ERR_MAX],
                             latency_ms=(time.monotonic() - start) * 1000)
        update: dict[str, object] = {"locale": locale, "dimension": dimension}
        if field is not None:
            update["field"] = field
        if not grounding:
            update["guideline_ref"] = None
        verdict = result.output.model_copy(update=update)
        return JudgeVote(judge=self.name, status="voted", verdict=verdict,
                         latency_ms=(time.monotonic() - start) * 1000)


def _model_ref(spec: "JudgeSpec"):
    """Resolve a JudgeSpec to a pydantic-ai model reference.

    anthropic -> "anthropic:<model>" (deferred by the Agent). openai (and any
    OpenAI-compatible base_url) -> an OpenAI model carrying base_url + key. See
    Task 4 Step 0: use the class the installed pydantic-ai exposes.
    """
    if spec.provider == "anthropic":
        return f"anthropic:{spec.model}"
    from pydantic_ai.models.openai import OpenAIModel  # or OpenAIChatModel (Step 0)
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        base_url=spec.base_url or "https://api.openai.com/v1",
        api_key=spec.api_key or "not-needed",   # local servers ignore it; client needs non-empty
    )
    return OpenAIModel(spec.model, provider=provider)
```

- [ ] **Step 4: Run tests + lint** — `uv run pytest tests/test_client.py -q` → PASS. `uv run ruff check src/asc_metadata_verifier/judge/client.py`.

- [ ] **Step 5: Commit** — `git commit -am "feat(jury): JudgeClient (async text+vision, error-isolated, honesty-preserving)"`

---

## Task 5: Judge config — specs, YAML loader, CLI mini-syntax

**Files:**
- Create: `src/asc_metadata_verifier/judge/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- `JudgeSpec(BaseModel)`: `name: str`, `provider: Literal["anthropic","openai"]`, `model: str`, `api_key_env: str | None = None`, `base_url: str | None = None`, `vision: bool = False`, `available: bool = True`, `api_key: str | None = None` (last two resolved at load; not read from YAML — YAML keys other than the first six are ignored/rejected).
- `JudgeSet` (dataclass): `specs: list[JudgeSpec]`, `consensus: str`.
- `load_judges(path) -> JudgeSet` — parse+validate+resolve availability. `judges_from_cli(specs: list[str]) -> list[JudgeSpec]`. `merge_specs(file_specs, cli_specs) -> list[JudgeSpec]` (CLI overrides file by `name`, appends new). `JudgeConfigError(Exception)`.
- **Availability resolution:** default `api_key_env` when absent — anthropic→`ANTHROPIC_API_KEY`, openai→`OPENAI_API_KEY`. Resolve `key = os.environ.get(api_key_env)`. `available = key is not None or base_url is not None`. `api_key = key` (unchanged; `client._model_ref` substitutes the `"not-needed"` placeholder for a keyless base_url). A spec that is unavailable stays in the list with `available=False` (the panel drops it and logs).
- **Validation → `JudgeConfigError`:** malformed YAML; top-level not a mapping; `judges` missing/empty; unknown `provider`; duplicate `name`; `consensus` not in `POLICIES`. Use `POLICIES` from `judge.consensus` to validate the consensus name.

- [ ] **Step 1: Write failing tests** — `tests/test_config.py`:

```python
import pytest

from asc_metadata_verifier.judge.config import (
    JudgeConfigError, judges_from_cli, load_judges, merge_specs,
)


def _write(tmp_path, text):
    p = tmp_path / "judges.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_specs_and_resolves_availability(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = _write(tmp_path, """
consensus: most_severe
judges:
  - {name: claude, provider: anthropic, model: claude-sonnet-5, vision: true}
  - {name: gpt4o, provider: openai, model: gpt-4o, api_key_env: OPENAI_API_KEY}
  - {name: local, provider: openai, model: llama3, base_url: http://localhost:11434/v1}
""")
    js = load_judges(p)
    assert js.consensus == "most_severe"
    by = {s.name: s for s in js.specs}
    assert by["claude"].available is True and by["claude"].vision is True
    assert by["gpt4o"].available is False            # OPENAI_API_KEY unset, no base_url
    assert by["local"].available is True             # base_url present, key not required


def test_default_consensus_is_majority_severe(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    p = _write(tmp_path, "judges:\n  - {name: c, provider: anthropic, model: m}\n")
    assert load_judges(p).consensus == "majority_severe"


def test_unknown_provider_raises(tmp_path):
    p = _write(tmp_path, "judges:\n  - {name: c, provider: gemini, model: m}\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_duplicate_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    p = _write(tmp_path, "judges:\n  - {name: c, provider: anthropic, model: m}\n  - {name: c, provider: anthropic, model: n}\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_bad_consensus_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    p = _write(tmp_path, "consensus: bogus\njudges:\n  - {name: c, provider: anthropic, model: m}\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_empty_judges_raises(tmp_path):
    p = _write(tmp_path, "judges: []\n")
    with pytest.raises(JudgeConfigError):
        load_judges(p)


def test_cli_mini_syntax_parses_named_and_bare_and_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    specs = judges_from_cli([
        "big=anthropic:claude-opus-4-8",
        "openai:gpt-4o",
        "local=openai:llama3@http://localhost:11434/v1",
    ])
    by = {s.name: s for s in specs}
    assert by["big"].provider == "anthropic" and by["big"].model == "claude-opus-4-8"
    assert by["local"].base_url == "http://localhost:11434/v1" and by["local"].available is True
    assert any(s.provider == "openai" and s.model == "gpt-4o" for s in specs)  # bare -> auto name


def test_merge_cli_overrides_file_by_name():
    from asc_metadata_verifier.judge.config import JudgeSpec
    file_specs = [JudgeSpec(name="claude", provider="anthropic", model="sonnet"),
                  JudgeSpec(name="gpt", provider="openai", model="gpt-4o")]
    cli_specs = [JudgeSpec(name="claude", provider="anthropic", model="opus")]
    merged = {s.name: s for s in merge_specs(file_specs, cli_specs)}
    assert merged["claude"].model == "opus" and "gpt" in merged and len(merged) == 2
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_config.py -q` → FAIL.

- [ ] **Step 3: Implement** — `src/asc_metadata_verifier/judge/config.py`. Parse YAML with `yaml.safe_load`; build `JudgeSpec`s (catch `pydantic.ValidationError` → `JudgeConfigError` with an actionable message); resolve availability; validate consensus against `POLICIES`; dedupe names. CLI mini-syntax: split on first `=` for the optional name, then `provider:model`, then optional `@base_url`; auto-name bare specs `judge{i}`; default `api_key_env` per provider; resolve availability the same way. `merge_specs`: start from file specs, replace-by-name or append CLI specs. Use `from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES`. Keep every error message free of secrets.

- [ ] **Step 4: Run tests + lint** — `uv run pytest tests/test_config.py -q` → PASS; ruff clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(jury): judges.yaml loader + --judge mini-syntax + availability resolution"`

---

## Task 6: JudgePanel — async orchestration (text + vision) + build_panel + run_panel

**Files:**
- Create: `src/asc_metadata_verifier/judge/panel.py`
- Test: `tests/test_panel.py`

**Interfaces:**
- `JudgePanel(clients, policy, policy_name, max_concurrency=8)` — `policy` is a `POLICIES[name]` callable. Holds `asyncio.Semaphore(max_concurrency)`.
- `async judge_text(meta, guidelines, dimensions) -> list[PanelVerdict]` — one `PanelVerdict` per (locale, dimension); each client's `run_text` gathered concurrently under the semaphore; `default_field="description"`.
- `async judge_vision(screenshots, guidelines, dimensions) -> list[PanelVerdict]` — reads each image **once** via `images.read_image` (unreadable → skipped like v1); returns `[]` immediately if no client `supports_vision`; else one `PanelVerdict` per (readable-screenshot, dimension), `field="screenshot"`, `default_field="screenshot"`.
- `run_panel(meta, guidelines, text_dimensions, *, screenshots=None, vision_dimensions=None, no_vision=False) -> list[PanelVerdict]` — sync wrapper: `asyncio.run` of text then (unless `no_vision`/empty/no-vision-client) vision, concatenated.
- `build_panel(specs, policy_name, max_concurrency=8) -> JudgePanel | None` — constructs `JudgeClient.from_spec` for `available` specs only; returns `None` if none available.
- The panel must accept **any** object with `name`, `supports_vision`, `async run_text`, `async run_vision` (duck-typed), so tests inject lightweight fakes.

- [ ] **Step 1: Write failing tests** — `tests/test_panel.py` (lightweight fake clients decoupled from real agents; they let us assert concurrency and provenance deterministically):

```python
import asyncio

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.consensus import POLICIES
from asc_metadata_verifier.judge.panel import JudgePanel
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.judge.vision import VISION_DIMENSIONS
from asc_metadata_verifier.models import (
    AppMetadata, JudgeVote, LocaleMetadata, RubricVerdict, Screenshot,
)

G = Guidelines(available=False, text="", sections={}, source="off")


class FakeClient:
    def __init__(self, name, verdict="fail", supports_vision=False, raise_text=False, tracker=None):
        self.name = name
        self.supports_vision = supports_vision
        self._verdict = verdict
        self._raise = raise_text
        self._t = tracker

    async def _vote(self):
        if self._t is not None:
            self._t["cur"] += 1
            self._t["max"] = max(self._t["max"], self._t["cur"])
            await asyncio.sleep(0.01)
            self._t["cur"] -= 1
        if self._raise:
            return JudgeVote(judge=self.name, status="error", error="boom")
        rv = RubricVerdict(dimension="d", verdict=self._verdict, severity="high",
                           confidence=0.9, rationale="r", locale="x", field="description")
        return JudgeVote(judge=self.name, status="voted", verdict=rv)

    async def run_text(self, dimension, locale_meta, grounding):
        return await self._vote()

    async def run_vision(self, screenshot, image_bytes, media_type, dimension, grounding):
        if not self.supports_vision:
            return JudgeVote(judge=self.name, status="not_applicable")
        return await self._vote()


def _panel(clients, name="majority_severe", mc=8):
    return JudgePanel(clients, POLICIES[name], name, max_concurrency=mc)


def _meta():
    return AppMetadata(locales=[LocaleMetadata(locale="en-US", description="x")])


def test_text_panel_one_paneleverdict_per_locale_dimension():
    panel = _panel([FakeClient("a"), FakeClient("b")])
    out = asyncio.run(panel.judge_text(_meta(), G, DIMENSIONS[:2]))
    assert len(out) == 2
    assert all(len(p.votes) == 2 and p.consensus.verdict == "fail" for p in out)
    assert out[0].policy == "majority_severe"


def test_error_isolation_one_judge_errors_other_still_votes():
    panel = _panel([FakeClient("ok"), FakeClient("bad", raise_text=True)])
    out = asyncio.run(panel.judge_text(_meta(), G, DIMENSIONS[:1]))
    p = out[0]
    assert p.consensus.verdict == "fail"           # the one voter carries it
    assert {v.status for v in p.votes} == {"voted", "error"}
    assert p.agreement == 1.0                       # over the single voter


def test_semaphore_caps_concurrency():
    tracker = {"cur": 0, "max": 0}
    clients = [FakeClient(f"c{i}", tracker=tracker) for i in range(6)]
    panel = _panel(clients, mc=2)
    asyncio.run(panel.judge_text(_meta(), G, DIMENSIONS[:3]))   # 3 units x 6 clients = 18 calls
    assert tracker["max"] <= 2


def test_vision_skipped_entirely_when_no_vision_client(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("text-only", supports_vision=False)])
    out = asyncio.run(panel.judge_vision([Screenshot(locale="en-US", path=str(png))], G, VISION_DIMENSIONS[:1]))
    assert out == []


def test_vision_runs_when_a_vision_client_present(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("v", supports_vision=True), FakeClient("t", supports_vision=False)])
    out = asyncio.run(panel.judge_vision([Screenshot(locale="en-US", path=str(png))], G, VISION_DIMENSIONS[:1]))
    assert len(out) == 1 and out[0].field == "screenshot"
    assert {v.status for v in out[0].votes} == {"voted", "not_applicable"}


def test_run_panel_sync_concatenates_text_and_vision(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("v", supports_vision=True)])
    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="x")],
                       screenshots=[Screenshot(locale="en-US", path=str(png))])
    out = panel.run_panel(meta, G, DIMENSIONS[:1],
                          screenshots=meta.screenshots, vision_dimensions=VISION_DIMENSIONS[:1])
    fields = {p.field for p in out}
    assert "screenshot" in fields and len(out) == 2   # 1 text + 1 vision


def test_run_panel_no_vision_flag_skips_vision(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("v", supports_vision=True)])
    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="x")],
                       screenshots=[Screenshot(locale="en-US", path=str(png))])
    out = panel.run_panel(meta, G, DIMENSIONS[:1], screenshots=meta.screenshots,
                          vision_dimensions=VISION_DIMENSIONS[:1], no_vision=True)
    assert all(p.field != "screenshot" for p in out) and len(out) == 1
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_panel.py -q` → FAIL.

- [ ] **Step 3: Implement** — `src/asc_metadata_verifier/judge/panel.py`:

```python
"""Concurrent panel of judges. Gathers each client's vote per unit under a
shared semaphore, then applies the consensus policy. Vision reads each image
once and dispatches the bytes to every client (non-vision clients return
not_applicable). Sync `run_panel` wraps the async work for the CLI (called
outside any running loop)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from asc_metadata_verifier.judge import images
from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.judge.client import JudgeClient
from asc_metadata_verifier.models import PanelVerdict

if TYPE_CHECKING:
    from asc_metadata_verifier.guidelines.source import Guidelines
    from asc_metadata_verifier.judge.config import JudgeSpec


class JudgePanel:
    def __init__(self, clients, policy, policy_name, max_concurrency=8):
        self.clients = list(clients)
        self.policy = policy
        self.policy_name = policy_name
        self._sem = asyncio.Semaphore(max_concurrency)

    async def _bounded(self, coro):
        async with self._sem:
            return await coro

    async def judge_text(self, meta, guidelines, dimensions) -> list[PanelVerdict]:
        units = [(lm, d) for lm in meta.locales for d in dimensions]

        async def one(lm, d):
            grounding = prompts.grounding_for_text(guidelines, d)
            votes = list(await asyncio.gather(
                *[self._bounded(c.run_text(d, lm, grounding)) for c in self.clients]
            ))
            cons, agr = self.policy(votes, locale=lm.locale, dimension=d.id,
                                    default_field="description")
            return PanelVerdict(locale=lm.locale, dimension=d.id, field=cons.field,
                                votes=votes, consensus=cons, policy=self.policy_name, agreement=agr)

        return list(await asyncio.gather(*[one(lm, d) for lm, d in units]))

    async def judge_vision(self, screenshots, guidelines, dimensions) -> list[PanelVerdict]:
        if not any(c.supports_vision for c in self.clients):
            return []
        prepared = []
        for s in screenshots:
            img = images.read_image(s)
            if img is not None:
                prepared.append((s, img))
        units = [(s, img, d) for (s, img) in prepared for d in dimensions]

        async def one(s, img, d):
            image_bytes, media_type = img
            grounding = prompts.grounding_for_vision(guidelines, d)
            votes = list(await asyncio.gather(
                *[self._bounded(c.run_vision(s, image_bytes, media_type, d, grounding))
                  for c in self.clients]
            ))
            cons, agr = self.policy(votes, locale=s.locale, dimension=d.id,
                                    default_field="screenshot")
            return PanelVerdict(locale=s.locale, dimension=d.id, field="screenshot",
                                votes=votes, consensus=cons, policy=self.policy_name, agreement=agr)

        return list(await asyncio.gather(*[one(s, img, d) for (s, img, d) in units]))

    def run_panel(self, meta, guidelines, text_dimensions, *, screenshots=None,
                  vision_dimensions=None, no_vision=False) -> list[PanelVerdict]:
        async def _all():
            text = await self.judge_text(meta, guidelines, text_dimensions)
            vision: list[PanelVerdict] = []
            if not no_vision and screenshots and vision_dimensions:
                vision = await self.judge_vision(screenshots, guidelines, vision_dimensions)
            return text + vision

        return asyncio.run(_all())


def build_panel(specs: "list[JudgeSpec]", policy_name: str, max_concurrency: int = 8):
    from asc_metadata_verifier.judge.consensus import POLICIES

    clients = [JudgeClient.from_spec(s) for s in specs if s.available]
    if not clients:
        return None
    return JudgePanel(clients, POLICIES[policy_name], policy_name, max_concurrency)
```

- [ ] **Step 4: Add the 1-judge≡v1 equivalence test** — append to `tests/test_panel.py` (proves the panel's single-judge consensus matches v1's `judge_field` verdict for the same model + inputs):

```python
def test_single_real_client_panel_matches_v1_judge_field():
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from asc_metadata_verifier.judge.agent import judge_field
    from asc_metadata_verifier.judge.client import JudgeClient

    def factory(_text):
        return RubricVerdict(dimension="echo", verdict="warn", severity="medium", confidence=0.8,
                             rationale="r", offending_quote="Android", guideline_ref=None,
                             suggested_fix="fix", locale="echo", field="description")

    def make_model():
        def fn(messages, info: AgentInfo):
            chunks = []
            for m in messages:
                for p in getattr(m, "parts", []):
                    if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                        chunks.append(p.content)
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, factory("\n".join(chunks)).model_dump())])
        return FunctionModel(fn)

    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="Also on Android")])
    v1 = judge_field(meta, G, DIMENSIONS[:1], model=make_model())[0]
    panel = _panel([JudgeClient.from_model("solo", make_model())])
    p = asyncio.run(panel.judge_text(meta, G, DIMENSIONS[:1]))[0]
    assert (p.consensus.verdict, p.consensus.severity, p.consensus.confidence) == \
           (v1.verdict, v1.severity, v1.confidence)
    assert p.consensus.locale == v1.locale and p.consensus.dimension == v1.dimension
    assert p.consensus.offending_quote == v1.offending_quote
```

- [ ] **Step 5: Run tests + lint** — `uv run pytest tests/test_panel.py -q` → PASS; ruff clean.

- [ ] **Step 6: Commit** — `git commit -am "feat(jury): concurrent JudgePanel (text+vision) + build_panel + 1-judge≡v1 test"`

---

## Task 7: Gate + report wiring

**Files:**
- Modify: `src/asc_metadata_verifier/gate.py`, `src/asc_metadata_verifier/report.py`
- Test: `tests/test_gate.py`, `tests/test_report.py`

**Interfaces:**
- `evaluate(verdicts, deterministic_findings, fail_on="fail", guidelines_available=True, panels=None)` — behavior on `verdicts`/findings is **unchanged**; `panels or []` is stored on `GateReport.panels`.
- `report.render_markdown` — after the verdicts section, when any panel has ≥2 voters, render a compact `## Panel deliberation` section: one line per such panel — `- en-US / placeholder_text: 3 judges → 2 fail / 1 pass (majority_severe ⇒ fail; agreement 0.67)`. `render_json` already includes `panels`.

- [ ] **Step 1: Write failing tests** — add to `tests/test_gate.py`:

```python
def test_evaluate_passes_panels_through_without_changing_status():
    from asc_metadata_verifier.gate import evaluate
    from asc_metadata_verifier.models import JudgeVote, PanelVerdict, RubricVerdict

    rv = RubricVerdict(dimension="placeholder_text", verdict="warn", severity="medium",
                       confidence=0.7, rationale="r", locale="en-US", field="description")
    panel = PanelVerdict(locale="en-US", dimension="placeholder_text", field="description",
                         votes=[JudgeVote(judge="a", status="voted", verdict=rv)],
                         consensus=rv, policy="majority_severe", agreement=1.0)
    report = evaluate([rv], [], panels=[panel])
    assert report.status == "WARN" and len(report.panels) == 1
    assert evaluate([rv], []).panels == []      # default stays empty
```

Add to `tests/test_report.py`:

```python
def test_markdown_shows_panel_deliberation_for_multi_voter_panels():
    from asc_metadata_verifier.models import GateReport, JudgeVote, PanelVerdict, RubricVerdict
    from asc_metadata_verifier.report import render_markdown

    def rv(v):
        return RubricVerdict(dimension="placeholder_text", verdict=v, severity="high",
                             confidence=0.9, rationale="r", locale="en-US", field="description")
    votes = [JudgeVote(judge="a", status="voted", verdict=rv("fail")),
             JudgeVote(judge="b", status="voted", verdict=rv("fail")),
             JudgeVote(judge="c", status="voted", verdict=rv("pass"))]
    panel = PanelVerdict(locale="en-US", dimension="placeholder_text", field="description",
                         votes=votes, consensus=rv("fail"), policy="majority_severe", agreement=2 / 3)
    md = render_markdown(GateReport(status="BLOCK", guidelines_available=True,
                                    verdicts=[rv("fail")], panels=[panel]))
    assert "Panel deliberation" in md
    assert "3 judges" in md and "majority_severe" in md


def test_markdown_omits_panel_section_when_no_multivoter_panels():
    from asc_metadata_verifier.models import GateReport
    from asc_metadata_verifier.report import render_markdown
    assert "Panel deliberation" not in render_markdown(
        GateReport(status="PASS", guidelines_available=True))
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_gate.py tests/test_report.py -q` → FAIL.

- [ ] **Step 3: Implement gate** — in `gate.py`, add `panels: list[PanelVerdict] | None = None` to `evaluate`'s signature (import `PanelVerdict`), and pass `panels=panels or []` into the returned `GateReport(...)`. Nothing else changes.

- [ ] **Step 4: Implement report** — in `report.py`, add:

```python
def _render_panels(panels: list[PanelVerdict]) -> list[str]:
    multi = [p for p in panels if sum(1 for v in p.votes if v.status == "voted") >= 2]
    if not multi:
        return []
    lines = ["## Panel deliberation", ""]
    for p in multi:
        voters = [v for v in p.votes if v.status == "voted"]
        tally = Counter(v.verdict.verdict for v in voters)
        breakdown = " / ".join(f"{n} {vd}" for vd, n in tally.most_common())
        agr = "n/a" if p.agreement is None else f"{p.agreement:.2f}"
        lines.append(
            f"- **{p.locale} / {p.dimension}**: {len(voters)} judges → {breakdown} "
            f"({p.policy} ⇒ {p.consensus.verdict}; agreement {agr})"
        )
    lines.append("")
    return lines
```

Import `PanelVerdict` and `Counter` (`from collections import Counter, defaultdict`), and in `render_markdown` insert `lines.extend(_render_panels(report.panels))` **after** `_render_verdicts` and before `_render_findings`.

- [ ] **Step 5: Run tests + lint** — `uv run pytest tests/test_gate.py tests/test_report.py -q` → PASS; ruff clean.

- [ ] **Step 6: Commit** — `git commit -am "feat(jury): gate passthrough + panel-deliberation markdown section"`

---

## Task 8: CLI wiring + judges.example.yaml

**Files:**
- Modify: `src/asc_metadata_verifier/cli.py`
- Create: `judges.example.yaml`
- Test: add `TestJuryPath` to `tests/test_cli.py`

**Interfaces:**
- New `verify`/`run_verify` params: `judges_path: Path | None` (`--judges`), `judge_cli: list[str]` (`--judge`, repeatable), `consensus: str | None` (`--consensus`), `max_concurrency: int = 8` (`--max-concurrency`).
- **Jury activation:** `jury_requested = bool(judges_path or judge_cli)`. When true and not `--dry-run`: build the `JudgeSet` (`_build_judge_set`), `build_panel`; if `None` (all judges unavailable) → `llm_skipped=True` (deterministic-only, like v1 no-key); else `panels = panel.run_panel(meta, guidelines, DIMENSIONS, screenshots=meta.screenshots, vision_dimensions=VISION_DIMENSIONS, no_vision=no_vision)`, `verdicts=[p.consensus for p in panels]`, `llm_skipped=False`.
- **When not `jury_requested`:** the v1 path runs **verbatim** (unchanged `judge_field`/`judge_screenshots`, key gating) — so every existing test passes untouched.
- `--consensus` given without `--judges`/`--judge` → `typer.BadParameter`. `consensus` defaults from the file (or `DEFAULT_POLICY`); `--consensus` overrides.
- `JudgeConfigError` is caught in `verify` and rendered like `IngestError` (`Error: ...`, exit code 2, no traceback).
- Pass `panels=panels` to `evaluate`. Import `build_panel`, `DEFAULT_POLICY`/`POLICIES`, `JudgeConfigError`, config loaders, and `VISION_DIMENSIONS` at module level (keeps them monkeypatchable and consistent with v1's import style).

- [ ] **Step 1: Write failing tests** — add to `tests/test_cli.py`:

```python
class TestJuryPath:
    def _judges_file(self, tmp_path):
        p = tmp_path / "judges.yaml"
        p.write_text(
            "consensus: most_severe\n"
            "judges:\n"
            "  - {name: a, provider: anthropic, model: claude-sonnet-5}\n"
            "  - {name: b, provider: anthropic, model: claude-opus-4-8}\n",
            encoding="utf-8",
        )
        return p

    def test_jury_runs_panel_and_emits_panels_in_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)

        # Stub build_panel to avoid real models: a panel whose run_panel returns
        # one BLOCK-worthy PanelVerdict.
        from asc_metadata_verifier.models import JudgeVote, PanelVerdict, RubricVerdict

        rv = RubricVerdict(dimension="placeholder_text", verdict="fail", severity="high",
                           confidence=0.9, rationale="r", offending_quote="Lorem",
                           locale="en-US", field="description")

        class StubPanel:
            def run_panel(self, *a, **k):
                return [PanelVerdict(locale="en-US", dimension="placeholder_text",
                                     field="description",
                                     votes=[JudgeVote(judge="a", status="voted", verdict=rv),
                                            JudgeVote(judge="b", status="voted", verdict=rv)],
                                     consensus=rv, policy="most_severe", agreement=1.0)]

        monkeypatch.setattr(cli, "build_panel", lambda *a, **k: StubPanel())

        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--judges",
                                         str(self._judges_file(tmp_path)), "--format", "json"])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "BLOCK"
        assert len(payload["panels"]) == 1
        assert payload["panels"][0]["votes"][0]["judge"] == "a"

    def test_all_unavailable_judges_degrades_to_deterministic(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(cli, "get_guidelines", _unavailable_guidelines)
        p = tmp_path / "j.yaml"
        p.write_text("judges:\n  - {name: g, provider: openai, model: gpt-4o, api_key_env: OPENAI_API_KEY}\n",
                     encoding="utf-8")
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--no-vision", "--judges", str(p)])
        assert result.exit_code == 0, result.output
        assert "LLM checks skipped" in result.output

    def test_consensus_without_judges_is_a_usage_error(self):
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--consensus", "most_severe"])
        assert result.exit_code == 2 and "Traceback" not in result.output

    def test_bad_consensus_name_exits_2_actionably(self, tmp_path):
        p = self._judges_file(tmp_path)
        result = runner.invoke(cli.app, [FIXTURE_ROOT, "--judges", str(p), "--consensus", "bogus"])
        assert result.exit_code == 2 and "Traceback" not in result.output
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_cli.py::TestJuryPath -q` → FAIL.

- [ ] **Step 3: Implement** — add the module-level imports and a `_build_judge_set(judges_path, judge_cli, consensus_override)` helper (raises `JudgeConfigError`/`typer.BadParameter`). Thread the four new params through `verify` → `run_verify`. Insert the jury branch inside the `if not dry_run:` block, before the v1 judge block, guarded by `jury_requested`; when jury runs, skip the v1 judge block. Add `panels` to the `evaluate(...)` call. Extend the `verify` `except` to catch `JudgeConfigError` (message + exit 2). Keep the `--consensus`-without-jury `BadParameter` check early.

- [ ] **Step 4: Create `judges.example.yaml`** (repo root):

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

- [ ] **Step 5: Run the FULL suite + lint** — `uv run pytest -q` → all pass (v1 CLI/e2e tests untouched + new jury tests). `uv run ruff check .`.

- [ ] **Step 6: Commit** — `git commit -am "feat(jury): CLI --judges/--judge/--consensus/--max-concurrency + example config"`

---

## Task 9: Jury meta-eval — per-judge accuracy, inter-judge κ, jury-vs-single lift

**Files:**
- Create: `src/asc_metadata_verifier/evals/jury_eval.py`
- Test: `tests/test_jury_eval.py`

**Interfaces:**
- `fleiss_kappa(ratings: list[list[int]]) -> float` — `ratings[i]` = per-category counts for item `i` (rows sum to the same number of raters). Pure, unit-tested against a known value.
- `collect_grid(clients, dataset, guidelines) -> dict[str, dict[str, dict[str, str]]]` — returns `by_judge[judge][case_name][dimension] = verdict_str` by running every client over the full 8-dimension grid for every case (async internally; one `asyncio.run`). Reuses `prompts`/`DIMENSIONS`; offline with injected models.
- `JuryEvalReport` (dataclass): `per_judge_accuracy: dict[str, float]`, `per_judge_report: dict[str, MetaEvalReport]`, `inter_judge_kappa: dict[str, float]` (per dimension), `jury_accuracy: dict[str, float]` (per policy name), `best_single_accuracy: float`, `lift: dict[str, float]` (per policy: jury − best single).
- `run(clients=None, specs=None, guidelines=None, dataset=None) -> JuryEvalReport` — real path builds clients from `specs` (key-gated); offline tests inject `clients` (fakes/`from_model`). Per-judge accuracy via `meta_eval.run(model=<that judge's model>)` when a model is available, else computed from `collect_grid` using the same per-case rule as `meta_eval` (positive case correct iff its labeled dimension flagged; clean control correct iff nothing wrongly flagged).
- **Honesty:** the module docstring pre-registers the hypothesis ("an ensemble beats the best single judge on golden-set accuracy") and states that a **null/negative `lift` is a valid result to report unchanged.** `run` never inflates a denominator: it scores over all `dataset.cases`.

- [ ] **Step 1: Write failing tests** — `tests/test_jury_eval.py` (offline: fake clients + a tiny synthetic 2-case dataset; plus a κ worked example):

```python
import asyncio
import math

from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.models import JudgeVote, RubricVerdict


def test_fleiss_kappa_perfect_agreement_is_one():
    from asc_metadata_verifier.evals.jury_eval import fleiss_kappa
    # 3 items, 4 raters, 2 categories, all raters agree on each item
    ratings = [[4, 0], [0, 4], [4, 0]]
    assert abs(fleiss_kappa(ratings) - 1.0) < 1e-9


def test_fleiss_kappa_known_value():
    from asc_metadata_verifier.evals.jury_eval import fleiss_kappa
    # chance-level agreement -> kappa near 0
    ratings = [[2, 2], [2, 2], [2, 2]]
    assert abs(fleiss_kappa(ratings)) < 1e-9


class _FakeJudge:
    """A judge that flags a fixed dimension with a fixed verdict on the full grid."""
    def __init__(self, name, flag_dim, verdict="fail", supports_vision=False):
        self.name = name
        self.supports_vision = supports_vision
        self._flag = flag_dim
        self._verdict = verdict

    async def run_text(self, dimension, locale_meta, grounding):
        v = self._verdict if dimension.id == self._flag else "pass"
        rv = RubricVerdict(dimension=dimension.id, verdict=v, severity="high", confidence=0.9,
                           rationale="r", locale=locale_meta.locale, field="description")
        return JudgeVote(judge=self.name, status="voted", verdict=rv)

    async def run_vision(self, *a, **k):
        return JudgeVote(judge=self.name, status="not_applicable")


def _tiny_dataset():
    from pydantic_evals import Case, Dataset
    from asc_metadata_verifier.evals.dataset import CaseExpected, CaseInputs
    d0 = DIMENSIONS[0].id
    cases = [
        Case(name="00-pos", inputs=CaseInputs(text="Lorem ipsum", locale="en-US", field="description", dimension=d0),
             expected_output=CaseExpected(expected_dimension=d0, expected_verdict="fail"),
             metadata={"also_valid_dimensions": []}),
        Case(name="01-clean", inputs=CaseInputs(text="A calm timer.", locale="en-US", field="description", dimension="none"),
             expected_output=CaseExpected(expected_dimension="none", expected_verdict="pass"),
             metadata={"also_valid_dimensions": []}),
    ]
    return Dataset(name="tiny", cases=cases)


def test_run_offline_reports_perjudge_and_jury_accuracy_and_lift():
    from asc_metadata_verifier.evals.jury_eval import run
    good = _FakeJudge("good", DIMENSIONS[0].id)          # flags the labeled dim (perfect here)
    noisy = _FakeJudge("noisy", DIMENSIONS[1].id)        # never flags the labeled dim
    rep = run(clients=[good, noisy], dataset=_tiny_dataset())
    assert rep.per_judge_accuracy["good"] == 1.0
    assert set(rep.jury_accuracy) == {"majority_severe", "most_severe", "unanimous", "confidence_weighted"}
    # most_severe should catch the positive (good flags it) -> jury accuracy >= best single here
    assert rep.jury_accuracy["most_severe"] >= 0.5
    for policy, lift in rep.lift.items():
        assert math.isclose(lift, rep.jury_accuracy[policy] - rep.best_single_accuracy)
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_jury_eval.py -q` → FAIL.

- [ ] **Step 3: Implement** — `src/asc_metadata_verifier/evals/jury_eval.py`. Provide:
  - `fleiss_kappa` (standard formula: `P_i = (sum n_ij^2 - n) / (n(n-1))`, `P_bar = mean(P_i)`, `P_e = sum p_j^2` where `p_j = sum_i n_ij / (N*n)`, `kappa = (P_bar - P_e)/(1 - P_e)`; return `1.0` when `P_e == 1`).
  - `collect_grid`: build the grid per judge via an internal `async` gather over `dataset.cases × DIMENSIONS`, using `_locale_meta_for` from `meta_eval` and `prompts.grounding_for_text`; one top-level `asyncio.run`.
  - per-case accuracy helper mirroring `meta_eval`'s rule (import `FLAGGED`, `_DIM_IDS`, reuse where possible).
  - `inter_judge_kappa`: per dimension, build `ratings` over cases with 2 categories (flagged / not-flagged) across judges, call `fleiss_kappa`.
  - jury accuracy per policy: for each case build synthetic `JudgeVote`s per dimension from the collected verdicts, apply each `POLICIES[name]` to get the jury's per-cell verdict, then score accuracy with the same rule.
  - `run`: offline uses injected `clients`; real path builds from `specs` (guarded so a real run scores all cases). Compute `best_single_accuracy = max(per_judge_accuracy.values())` and `lift[policy] = jury_accuracy[policy] - best_single_accuracy`.
  - Module docstring pre-registers the hypothesis and the null-result honesty note.

- [ ] **Step 4: Run tests + lint** — `uv run pytest tests/test_jury_eval.py -q` → PASS; ruff clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(jury): meta-eval — per-judge accuracy, Fleiss κ, jury-vs-single lift"`

---

## Task 10: Documentation — README jury section + honest BUILD_LOG

**Files:**
- Modify: `README.md`, `BUILD_LOG.md`

- [ ] **Step 1: README** — add a "Multi-LLM jury (optional)" section after the existing usage: what it is; the `judges.yaml` schema (env-var refs only) with a copy of `judges.example.yaml`; the four `--consensus` policies (one line each); `--judge`/`--max-concurrency`; the self-hosted note (any OpenAI-compatible `base_url`); and the honest status — "the default (no `--judges`) is unchanged single-Claude v1; the jury and its accuracy claims are validated offline with synthetic judges, and the real-model agreement/lift numbers require API keys (`evals/jury_eval.py`, not yet run against live models)." No fabricated numbers.

- [ ] **Step 2: BUILD_LOG** — append a v2/jury entry recording: the design decisions (default-path-unchanged vs one-code-path; the exact pydantic-ai OpenAI class used from Task 4 Step 0; the empty-tally→flagged-pass rule; unavailable-judge omit-at-build); which tasks took fix rounds; and the honest open items (real-model per-judge accuracy, inter-judge κ, and jury-vs-single lift **not yet run** — pre-registered, no numbers fabricated). Pre-register the ensemble-lift hypothesis here **before** any real-model run.

- [ ] **Step 3: Run the full suite once more** — `uv run pytest -q` (all green) and `uv run ruff check .`.

- [ ] **Step 4: Commit** — `git commit -am "docs(jury): README jury usage + honest BUILD_LOG entry"`

---

## Self-Review (author checklist — completed)

**Spec coverage:** panel abstraction (T4/T6) · 4 selectable consensus policies + default (T2) · text+vision jury (T4/T6) · config file + CLI override + secrets-by-ref (T5/T8) · concurrency + semaphore (T6) · degrade-and-record on failure/unavailable (T4/T6/T8) · backward-compatible default + 1-judge≡v1 test (T6/T8) · panel votes in JSON + markdown (T7) · Logfire per-judge spans (folded into T6 via the existing `span`/`instrument_pydantic_ai`; the panel runs under the CLI's `span("judge")` and pydantic-ai auto-instruments each `agent.run`) · jury meta-eval with κ + null-result discipline (T9) · judges.example.yaml + docs (T8/T10). All spec sections map to a task.

**Placeholder scan:** no TBD/TODO; every code step has real code; the one genuinely-unknown external API (pydantic-ai OpenAI class name at the installed version) is handled by an explicit verification step (T4 Step 0), not a guess — consistent with the honesty bar.

**Type consistency:** `JudgeVote`/`PanelVerdict`/`GateReport.panels` (T1) are used identically in T2/T4/T6/T7/T8/T9. Consensus signature `policy(votes, *, locale, dimension, default_field)` is consistent across T2 (def), T6 (call). `JudgeClient.run_text(dimension, locale_meta, grounding)` / `run_vision(screenshot, image_bytes, media_type, dimension, grounding)` consistent across T4 (def) and T6 (call). `build_panel(specs, policy_name, max_concurrency)` consistent T6↔T8. `JudgeSpec` fields consistent T5↔T4 (`_model_ref` reads `provider/model/base_url/api_key/vision`).

**One refinement from the spec (flag to the user at handoff):** the spec framed the default as "a 1-judge Claude panel, one code path." The plan instead keeps the v1 default path **literally unchanged** and activates the panel only when a jury is configured — this is strictly safer (every v1 test stays green; no `asyncio.run` nested inside pydantic-evals' sync evaluator) and still delivers "byte-identical v1 default" and "1-judge ≡ v1" (proven by a panel-level equivalence test). Everything else matches the spec.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-09-multi-llm-jury.md`.** Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, spec+quality review gate after each, whole-branch review at the end (same method that built v1).

**2. Inline Execution** — execute tasks in this session with checkpoints.

**Which approach?**
