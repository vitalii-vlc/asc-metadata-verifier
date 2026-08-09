"""Offline tests for the jury meta-eval (Task 9).

Fully offline: content-aware fake judges (async ``run_text``) + a tiny synthetic
2-case dataset, plus Fleiss' kappa worked examples. No network, no API key.

Two deliberate corrections to the original task brief's draft tests, both to keep
every asserted number the REAL output of the REAL computation (no massaging):

  * The "chance-level" kappa example uses ``[[3,1],[1,3]]`` (genuine chance:
    P_bar == P_e == 0.5 -> kappa == 0.0 exactly under the standard formula). The
    draft's ``[[2,2],[2,2],[2,2]]`` is *maximal below-chance* disagreement and
    yields -1/3, not 0 -- pinned separately below so it is never silently clamped.
  * The fake judges are CONTENT-AWARE, so ``good`` is a *genuinely* perfect judge
    (accuracy 1.0) under meta_eval's UNCHANGED per-case rule. A content-independent
    stub that flagged its dimension on every case would false-positive on the clean
    control and could never legitimately reach 1.0.
"""

import math

from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.models import JudgeVote, RubricVerdict


def test_fleiss_kappa_perfect_agreement_is_one():
    from asc_metadata_verifier.evals.jury_eval import fleiss_kappa

    # 3 items, 4 raters, 2 categories, all raters agree on each item.
    ratings = [[4, 0], [0, 4], [4, 0]]
    assert abs(fleiss_kappa(ratings) - 1.0) < 1e-9


def test_fleiss_kappa_chance_level_is_zero():
    from asc_metadata_verifier.evals.jury_eval import fleiss_kappa

    # Genuine chance-level agreement: observed P_bar == chance P_e == 0.5, so
    # kappa == 0 EXACTLY under the standard formula.
    ratings = [[3, 1], [1, 3]]
    assert abs(fleiss_kappa(ratings)) < 1e-9


def test_fleiss_kappa_below_chance_is_negative():
    from asc_metadata_verifier.evals.jury_eval import fleiss_kappa

    # Every item split exactly 2-2 => raters agree LESS than chance => kappa < 0.
    # Pinned so the honest below-chance value is never silently clamped to 0.
    ratings = [[2, 2], [2, 2], [2, 2]]
    assert math.isclose(fleiss_kappa(ratings), -1.0 / 3.0, rel_tol=1e-9)


class _FakeJudge:
    """A CONTENT-AWARE judge: flags ``flag_dim`` iff the case text contains one of
    ``triggers``; otherwise it passes every dimension. Models an honest judge that
    fires only on cases whose text actually trips its dimension.
    """

    def __init__(self, name, flag_dim, triggers, verdict="fail", supports_vision=False):
        self.name = name
        self.supports_vision = supports_vision
        self._flag = flag_dim
        self._triggers = tuple(t.lower() for t in triggers)
        self._verdict = verdict

    async def run_text(self, dimension, locale_meta, grounding):
        text = " ".join(
            v for v in locale_meta.model_dump().values() if isinstance(v, str)
        ).lower()
        fires = dimension.id == self._flag and any(t in text for t in self._triggers)
        v = self._verdict if fires else "pass"
        rv = RubricVerdict(
            dimension=dimension.id, verdict=v, severity="high", confidence=0.9,
            rationale="r", locale=locale_meta.locale, field="description",
        )
        return JudgeVote(judge=self.name, status="voted", verdict=rv)

    async def run_vision(self, *a, **k):
        return JudgeVote(judge=self.name, status="not_applicable")


def _tiny_dataset():
    from pydantic_evals import Case, Dataset

    from asc_metadata_verifier.evals.dataset import CaseExpected, CaseInputs

    d0 = DIMENSIONS[0].id
    cases = [
        Case(
            name="00-pos",
            inputs=CaseInputs(
                text="Lorem ipsum", locale="en-US", field="description", dimension=d0
            ),
            expected_output=CaseExpected(expected_dimension=d0, expected_verdict="fail"),
            metadata={"also_valid_dimensions": []},
        ),
        Case(
            name="01-clean",
            inputs=CaseInputs(
                text="A calm timer.", locale="en-US", field="description", dimension="none"
            ),
            expected_output=CaseExpected(expected_dimension="none", expected_verdict="pass"),
            metadata={"also_valid_dimensions": []},
        ),
    ]
    return Dataset(name="tiny", cases=cases)


def test_run_offline_reports_perjudge_and_jury_accuracy_and_lift():
    from asc_metadata_verifier.evals.jury_eval import run

    # good: flags placeholder_text (d0) only on placeholder-looking text ("Lorem
    #       ipsum") -> perfect on this dataset (correct on the positive, clean on
    #       the control).
    # noisy: mis-attributes that same placeholder text to a DIFFERENT dimension
    #        (d1) and never flags d0 -> genuinely worse; its trigger words appear
    #        only in the positive case so it stays clean on the control.
    good = _FakeJudge("good", DIMENSIONS[0].id, triggers=("ipsum", "lorem"))
    noisy = _FakeJudge("noisy", DIMENSIONS[1].id, triggers=("ipsum", "lorem"))
    rep = run(clients=[good, noisy], dataset=_tiny_dataset())

    assert rep.per_judge_accuracy["good"] == 1.0
    assert set(rep.jury_accuracy) == {
        "majority_severe", "most_severe", "unanimous", "confidence_weighted"
    }
    # most_severe catches the positive (good flags it) and stays clean on the
    # control (noisy's trigger words are absent there) -> jury accuracy >= 0.5.
    assert rep.jury_accuracy["most_severe"] >= 0.5
    for policy, lift in rep.lift.items():
        assert math.isclose(lift, rep.jury_accuracy[policy] - rep.best_single_accuracy)


def _meta_report(n_cases):
    """Minimal MetaEvalReport carrying only the fields the guard inspects."""
    from asc_metadata_verifier.evals.meta_eval import MetaEvalReport

    return MetaEvalReport(
        per_dimension_precision={},
        per_dimension_recall={},
        accuracy=1.0,
        failure_taxonomy={},
        per_dimension_counts={},
        n_cases=n_cases,
    )


def test_require_full_denominator_rejects_shrunken_report():
    # Real-path guard: a per-judge report that scored fewer than ALL cases must
    # be refused (a failed model call would else inflate accuracy -> lift).
    import pytest

    from asc_metadata_verifier.evals.jury_eval import _require_full_denominator

    with pytest.raises(RuntimeError, match=r"scored 4/5 cases"):
        _require_full_denominator(_meta_report(n_cases=4), expected_n=5, judge_name="j1")


def test_require_full_denominator_accepts_full_report():
    from asc_metadata_verifier.evals.jury_eval import _require_full_denominator

    report = _meta_report(n_cases=5)
    assert _require_full_denominator(report, expected_n=5, judge_name="j1") is report
