"""Judge-vs-ground-truth meta-eval over the golden dataset (Task 13).

Runs the rejection-risk judge (``judge_field``) over every golden case and the
FULL 8-dimension grid, then computes agreement statistics against the curated
labels. See ``BUILD_LOG.md`` for the pre-registered methodology.

Methodology (full grid, one-vs-rest):
  For each golden case we run the judge on ALL 8 rubric dimensions (not only the
  labeled one). Each (case, dimension) cell is a prediction: the judge "flagged"
  the dimension iff its verdict is ``warn`` or ``fail`` (``pass`` = not flagged).
  Ground truth for a cell is flagged iff the case's ``expected_dimension`` equals
  that dimension AND the case is a positive (``expected_verdict`` in warn/fail).

  Running the full grid (rather than only each case's own dimension) is the
  sounder choice: it is the only way to observe cross-dimension FALSE POSITIVES
  -- e.g. a clean control that says "expandable" wrongly tripping placeholder,
  or a price case wrongly tripping keyword_stuffing. Cost is bounded only by the
  key gate: offline (FunctionModel) it is free; the real-model path is
  N_cases x 8 calls and gated behind ANTHROPIC_API_KEY. No cases are skipped.

  Per dimension D:  precision = TP / (TP + FP),  recall = TP / (TP + FN).
  Zero-denominator convention (documented): reported as 0.0 (sklearn's default),
  so a judge that never flags D does not get a misleading precision of 1.0.

  Accuracy is per-CASE binary detection (matching the label's flag/no-flag
  class): a positive case is correct iff the judge flags its labeled dimension;
  a clean control is correct iff the judge flags NO dimension. Severity/tier
  mismatches and cross-dimension flags do not change this binary number but ARE
  recorded in ``failure_taxonomy`` for debugging.

Offline by construction: ``run(model=<FunctionModel>)`` needs no network/key.
The real-model path (``model=None`` -> ``build_judge`` default) is gated behind
ANTHROPIC_API_KEY and is NOT run in the dev environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from asc_metadata_verifier.evals.dataset import CaseExpected, CaseInputs, build_dataset
from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.agent import judge_field
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_evals import Dataset
    from pydantic_evals.reporting import EvaluationReport

FLAGGED = {"warn", "fail"}
_DIM_IDS = [d.id for d in DIMENSIONS]
# Which LocaleMetadata attribute the case text lives in, per its `field` label.
_LOCALE_FIELDS = set(LocaleMetadata.model_fields)


class JudgedCell(BaseModel):
    """The judge's verdict for one (case, dimension) grid cell."""

    verdict: str
    severity: str
    offending_quote: str | None = None

    @property
    def flagged(self) -> bool:
        return self.verdict in FLAGGED


class GridOutput(BaseModel):
    """The judge's verdicts for one case across all 8 dimensions."""

    cells: dict[str, JudgedCell]


@dataclass
class FailureRecord:
    """One judge miss, captured with enough context to debug it."""

    case_name: str
    dimension: str
    category: str  # false_positive | false_negative | wrong_dimension | wrong_severity
    expected_verdict: str
    got_verdict: str
    text_snippet: str
    detail: str = ""


_CATEGORIES = ("false_negative", "false_positive", "wrong_dimension", "wrong_severity")


@dataclass
class MetaEvalReport:
    """Judge-vs-ground-truth agreement over the golden set."""

    per_dimension_precision: dict[str, float]
    per_dimension_recall: dict[str, float]
    accuracy: float
    failure_taxonomy: dict[str, list[FailureRecord]]
    per_dimension_counts: dict[str, dict[str, int]]
    n_cases: int

    def total_failures(self) -> int:
        return sum(len(v) for v in self.failure_taxonomy.values())

    def all_failures(self) -> list[FailureRecord]:
        return [rec for recs in self.failure_taxonomy.values() for rec in recs]


def _offline_guidelines() -> Guidelines:
    """Grounding-free guidelines: no network, no key, no fabrication."""
    return Guidelines(available=False, text="", sections={}, source="offline")


def _locale_meta_for(inp: CaseInputs) -> LocaleMetadata:
    """Place the case text into the labeled metadata field (default description)."""
    attr = inp.field if inp.field in _LOCALE_FIELDS else "description"
    return LocaleMetadata(locale=inp.locale, **{attr: inp.text})


def _make_task(model, guidelines: Guidelines):
    def task(inp: CaseInputs) -> GridOutput:
        meta = AppMetadata(locales=[_locale_meta_for(inp)])
        verdicts = judge_field(meta, guidelines, DIMENSIONS, model=model)
        return GridOutput(
            cells={
                v.dimension: JudgedCell(
                    verdict=v.verdict,
                    severity=v.severity,
                    offending_quote=v.offending_quote,
                )
                for v in verdicts
            }
        )

    return task


def _precision(tp: int, fp: int) -> float:
    denom = tp + fp
    return tp / denom if denom else 0.0  # zero_division -> 0.0 (documented)


def _recall(tp: int, fn: int) -> float:
    denom = tp + fn
    return tp / denom if denom else 0.0  # zero_division -> 0.0 (documented)


def _snippet(text: str, limit: int = 120) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _aggregate(report: EvaluationReport) -> MetaEvalReport:
    counts = {dim: {"TP": 0, "FP": 0, "FN": 0, "TN": 0} for dim in _DIM_IDS}
    taxonomy: dict[str, list[FailureRecord]] = {cat: [] for cat in _CATEGORIES}
    correct_cases = 0
    n_cases = 0

    for rc in report.cases:
        n_cases += 1
        inp: CaseInputs = rc.inputs
        expected: CaseExpected = rc.expected_output
        out: GridOutput = rc.output
        exp_dim = expected.expected_dimension
        exp_verdict = expected.expected_verdict
        snippet = _snippet(inp.text)

        flagged_dims = [dim for dim in _DIM_IDS if out.cells[dim].flagged]

        # --- grid counts (one-vs-rest per dimension) ---
        for dim in _DIM_IDS:
            judged_flag = out.cells[dim].flagged
            truth_flag = dim == exp_dim and exp_verdict in FLAGGED
            if truth_flag and judged_flag:
                counts[dim]["TP"] += 1
            elif truth_flag and not judged_flag:
                counts[dim]["FN"] += 1
            elif (not truth_flag) and judged_flag:
                counts[dim]["FP"] += 1
            else:
                counts[dim]["TN"] += 1

        # --- per-case accuracy + failure taxonomy ---
        is_positive = exp_dim != "none" and exp_verdict in FLAGGED
        if is_positive:
            target = out.cells[exp_dim]
            if target.flagged:
                correct_cases += 1
                if target.verdict != exp_verdict:  # detected, wrong tier
                    taxonomy["wrong_severity"].append(
                        FailureRecord(
                            rc.name, exp_dim, "wrong_severity", exp_verdict,
                            target.verdict, snippet, "flagged but different severity tier",
                        )
                    )
            else:  # missed the labeled dimension
                taxonomy["false_negative"].append(
                    FailureRecord(
                        rc.name, exp_dim, "false_negative", exp_verdict,
                        target.verdict, snippet,
                    )
                )
                other = [dim for dim in flagged_dims if dim != exp_dim]
                if other:  # missed target but flagged something else
                    taxonomy["wrong_dimension"].append(
                        FailureRecord(
                            rc.name, exp_dim, "wrong_dimension", exp_verdict,
                            "pass", snippet, f"judge instead flagged: {', '.join(other)}",
                        )
                    )
            # cross-dimension false positives on a positive case
            for dim in flagged_dims:
                if dim != exp_dim:
                    taxonomy["false_positive"].append(
                        FailureRecord(
                            rc.name, dim, "false_positive", "pass",
                            out.cells[dim].verdict, snippet,
                            "extra flag on a non-labeled dimension",
                        )
                    )
        else:  # clean control: correct iff nothing flagged
            if not flagged_dims:
                correct_cases += 1
            else:
                for dim in flagged_dims:
                    taxonomy["false_positive"].append(
                        FailureRecord(
                            rc.name, dim, "false_positive", "pass",
                            out.cells[dim].verdict, snippet,
                            "flagged a clean control",
                        )
                    )

    precision = {dim: _precision(counts[dim]["TP"], counts[dim]["FP"]) for dim in _DIM_IDS}
    recall = {dim: _recall(counts[dim]["TP"], counts[dim]["FN"]) for dim in _DIM_IDS}
    accuracy = correct_cases / n_cases if n_cases else 0.0

    return MetaEvalReport(
        per_dimension_precision=precision,
        per_dimension_recall=recall,
        accuracy=accuracy,
        failure_taxonomy=taxonomy,
        per_dimension_counts=counts,
        n_cases=n_cases,
    )


def run(
    model: Model | str | None = None,
    guidelines: Guidelines | None = None,
    dataset: Dataset | None = None,
) -> MetaEvalReport:
    """Run the judge over the golden set and compute agreement statistics.

    - ``model`` is passed straight through to ``judge_field``. Offline tests
      inject a ``FunctionModel``/``TestModel``; ``model=None`` uses the default
      Anthropic judge (requires ANTHROPIC_API_KEY at run time -- the real-model
      path, not run in the dev environment).
    - ``guidelines`` defaults to a grounding-free, offline-safe object (no
      network, no key). A real-model run may pass live guidelines.
    - ``dataset`` defaults to ``build_dataset()``.
    """
    if dataset is None:
        dataset = build_dataset()
    if guidelines is None:
        guidelines = _offline_guidelines()

    task = _make_task(model, guidelines)
    report = dataset.evaluate_sync(task, progress=False)
    return _aggregate(report)
