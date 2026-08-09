"""Jury meta-eval: does an ensemble of judges beat the best single judge? (Task 9)

PRE-REGISTERED HYPOTHESIS
    An ensemble (jury) of independent LLM judges achieves HIGHER golden-set
    per-case accuracy than the single best individual judge.

    The primary quantity is ``lift[policy] = jury_accuracy[policy] -
    best_single_accuracy``. A NULL (zero) or NEGATIVE lift is a VALID, fully
    expected-possible outcome and MUST be reported UNCHANGED -- never massaged,
    clamped, or hidden. A jury can genuinely underperform its best member: a
    strict ``unanimous`` policy can be dragged below a strong judge by one
    dissenter, and ``most_severe`` can amplify a single judge's false positive.
    Reporting a negative lift honestly is the whole point of this module; there
    is no code path that floors ``lift`` at zero.

METHODOLOGY (reuses ``meta_eval`` -- no new scoring rule is invented)
    * Full grid: every judge is run over the FULL 8-dimension rubric for EVERY
      golden case (``collect_grid``), exactly like ``meta_eval`` -- the only way
      to observe cross-dimension false positives.
    * Per-case accuracy uses ``meta_eval``'s EXACT rule (``FLAGGED``, ``_DIM_IDS``
      imported from it): a positive case is correct iff its labeled dimension is
      flagged; a clean control is correct iff nothing is WRONGLY flagged (a flag
      on ``also_valid_dimensions`` is not wrong). The same helper scores both a
      single judge's grid and the jury's per-cell consensus, so ``lift`` is an
      apples-to-apples comparison on the offline path.
    * Per-judge accuracy comes from ``meta_eval.run(model=<that judge's model>)``
      when a model is available (real, key-gated path); with injected fake
      clients (offline) it is computed from ``collect_grid`` using that same rule.
      Both measurement paths wrap the same model through
      ``prompts.build_text_prompt``, so they agree.
    * Inter-judge agreement is Fleiss' kappa per dimension: for each dimension we
      build a per-case ``[flagged, not_flagged]`` count across judges and call
      ``fleiss_kappa`` (a dimension no judge ever flags => all agree => kappa 1.0).
    * Jury accuracy per consensus policy: for each (case, dimension) cell we build
      synthetic ``JudgeVote``s from the collected verdicts, apply each
      ``consensus.POLICIES[name]`` exactly as ``judge.panel`` does, read the
      consensus verdict, and score the case with the same per-case rule.

    The denominator is never inflated: accuracy is always over ALL
    ``dataset.cases``. No fabricated numbers -- every accuracy/agreement is
    computed from the judges' ACTUAL outputs (offline: the injected fakes' real
    outputs; real path: key-gated model calls, not run in this environment).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from asc_metadata_verifier.evals import meta_eval
from asc_metadata_verifier.evals.dataset import build_dataset
from asc_metadata_verifier.evals.meta_eval import (
    _DIM_IDS,
    FLAGGED,
    MetaEvalReport,
    _locale_meta_for,
    _offline_guidelines,
)
from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.judge.client import JudgeClient, _model_ref
from asc_metadata_verifier.judge.consensus import POLICIES
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.models import JudgeVote, RubricVerdict

if TYPE_CHECKING:
    from pydantic_evals import Dataset

    from asc_metadata_verifier.guidelines.source import Guidelines
    from asc_metadata_verifier.judge.config import JudgeSpec

# Verdict strings that constitute a "voted" verdict (vs an abstain/error status).
_VERDICT_STRS = {"pass", "warn", "fail"}
# Reconstruct a severity for a synthetic vote from its verdict (collect_grid only
# retains the verdict string, per its signature). Documented, deterministic map.
_SEVERITY_FOR_VERDICT = {"pass": "low", "warn": "medium", "fail": "high"}


@dataclass
class JuryEvalReport:
    """Jury-vs-single-judge agreement and accuracy over the golden set."""

    per_judge_accuracy: dict[str, float]
    per_judge_report: dict[str, MetaEvalReport]
    inter_judge_kappa: dict[str, float]  # per dimension
    jury_accuracy: dict[str, float]  # per consensus policy name
    best_single_accuracy: float
    lift: dict[str, float]  # per policy: jury_accuracy - best_single_accuracy


def fleiss_kappa(ratings: list[list[int]]) -> float:
    """Fleiss' kappa for N items x k categories.

    ``ratings[i][j]`` is the number of raters that assigned item ``i`` to
    category ``j`` (every row sums to the same number of raters ``n``).

    Standard formula::

        P_i   = (sum_j n_ij^2 - n) / (n(n-1))
        P_bar = mean_i P_i
        p_j   = (sum_i n_ij) / (N*n)
        P_e   = sum_j p_j^2
        kappa = (P_bar - P_e) / (1 - P_e)

    Returns ``1.0`` when ``P_e == 1`` (all raters in one category -> perfect
    agreement, and the ``(1 - P_e)`` denominator vanishes). Returns ``nan`` when
    kappa is undefined (fewer than 2 items, or fewer than 2 raters per item).

    This is the UNMODIFIED chance-corrected statistic: below-chance agreement
    yields a genuinely NEGATIVE value, which is reported as-is (never clamped).
    """
    n_items = len(ratings)
    if n_items == 0:
        return float("nan")
    n_raters = sum(ratings[0])
    if n_raters < 2:
        return float("nan")
    k = len(ratings[0])

    p_bar = sum(
        (sum(c * c for c in row) - n_raters) / (n_raters * (n_raters - 1))
        for row in ratings
    ) / n_items

    total = n_items * n_raters
    p_e = sum(
        (sum(ratings[i][j] for i in range(n_items)) / total) ** 2 for j in range(k)
    )
    if p_e >= 1.0:
        return 1.0
    return (p_bar - p_e) / (1.0 - p_e)


def _verdict_str(vote: JudgeVote) -> str:
    """The verdict string for a grid cell. A non-voted (abstain/error/
    not_applicable) vote contributes its status -- not in ``FLAGGED``, so it is
    treated as "not flagged" for accuracy and excluded from the jury tally."""
    if vote.status == "voted" and vote.verdict is not None:
        return vote.verdict.verdict
    return vote.status


def collect_grid(clients, dataset, guidelines) -> dict[str, dict[str, dict[str, str]]]:
    """Run every client over the full 8-dimension grid for every case.

    Returns ``by_judge[judge_name][case_name][dimension_id] = verdict_str``.
    Async internally (one gather over ``clients x cases x DIMENSIONS``) behind a
    single ``asyncio.run``. Offline-safe: injected fake clients only need an
    async ``run_text(dimension, locale_meta, grounding)``.
    """

    async def _run_all():
        metas = {case.name: _locale_meta_for(case.inputs) for case in dataset.cases}
        groundings = {
            dim.id: prompts.grounding_for_text(guidelines, dim) for dim in DIMENSIONS
        }

        async def cell(client, case, dim):
            vote = await client.run_text(dim, metas[case.name], groundings[dim.id])
            return client.name, case.name, dim.id, _verdict_str(vote)

        tasks = [
            cell(c, case, dim)
            for c in clients
            for case in dataset.cases
            for dim in DIMENSIONS
        ]
        results = await asyncio.gather(*tasks)

        grid: dict[str, dict[str, dict[str, str]]] = {
            c.name: {case.name: {} for case in dataset.cases} for c in clients
        }
        for judge_name, case_name, dim_id, verdict in results:
            grid[judge_name][case_name][dim_id] = verdict
        return grid

    return asyncio.run(_run_all())


def _also_valid(case) -> set[str]:
    return set((case.metadata or {}).get("also_valid_dimensions", []))


def _case_correct(flagged: dict[str, bool], expected, also_valid: set[str]) -> bool:
    """meta_eval's EXACT per-case accuracy rule, over a dim->flagged map.

    Positive case: correct iff its labeled dimension is flagged. Clean control:
    correct iff no dimension is WRONGLY flagged (a flag on ``also_valid`` is not
    wrong). Mirrors ``meta_eval._aggregate``.
    """
    exp_dim = expected.expected_dimension
    exp_verdict = expected.expected_verdict
    wrong_flags = [
        d for d in _DIM_IDS if flagged[d] and d != exp_dim and d not in also_valid
    ]
    is_positive = exp_dim != "none" and exp_verdict in FLAGGED
    if is_positive:
        return flagged.get(exp_dim, False)
    return not wrong_flags


def _flagged_from_verdicts(verdicts: dict[str, str]) -> dict[str, bool]:
    return {dim: verdicts.get(dim, "pass") in FLAGGED for dim in _DIM_IDS}


def _score_grid(grid_for_judge: dict[str, dict[str, str]], dataset) -> float:
    """Per-case accuracy of one judge over the whole dataset (all cases)."""
    n = len(dataset.cases)
    if not n:
        return 0.0
    correct = sum(
        _case_correct(
            _flagged_from_verdicts(grid_for_judge[case.name]),
            case.expected_output,
            _also_valid(case),
        )
        for case in dataset.cases
    )
    return correct / n


def _inter_judge_kappa(grid, judges, dataset) -> dict[str, float]:
    """Fleiss' kappa per dimension over the flagged/not-flagged decision."""
    n_judges = len(judges)
    kappa: dict[str, float] = {}
    for dim in _DIM_IDS:
        ratings: list[list[int]] = []
        for case in dataset.cases:
            flagged = sum(
                1 for j in judges if grid[j][case.name].get(dim, "pass") in FLAGGED
            )
            ratings.append([flagged, n_judges - flagged])
        kappa[dim] = fleiss_kappa(ratings)
    return kappa


def _synthetic_vote(judge_name: str, dim_id: str, verdict_str: str, locale: str) -> JudgeVote:
    """Rebuild a ``JudgeVote`` for one cell from a collected verdict string.

    A non-voted status (abstain/error/not_applicable) reconstructs a non-voted
    vote, which ``consensus`` excludes from the tally. Confidence is fixed (the
    grid retains only the verdict string); with equal confidences
    ``confidence_weighted`` degenerates to a summed-count majority -- documented.
    """
    if verdict_str not in _VERDICT_STRS:
        return JudgeVote(judge=judge_name, status=verdict_str)
    rv = RubricVerdict(
        dimension=dim_id,
        verdict=verdict_str,
        severity=_SEVERITY_FOR_VERDICT[verdict_str],
        confidence=1.0,
        rationale="reconstructed from collected grid verdict",
        locale=locale,
        field="description",
    )
    return JudgeVote(judge=judge_name, status="voted", verdict=rv)


def _jury_flagged(grid, judges, case, policy) -> dict[str, bool]:
    """Apply one consensus policy per cell and return the jury's dim->flagged map."""
    locale = case.inputs.locale
    flagged: dict[str, bool] = {}
    for dim in _DIM_IDS:
        votes = [
            _synthetic_vote(j, dim, grid[j][case.name].get(dim, "pass"), locale)
            for j in judges
        ]
        consensus, _agreement = policy(
            votes, locale=locale, dimension=dim, default_field="description"
        )
        flagged[dim] = consensus.verdict in FLAGGED
    return flagged


def _jury_accuracy(grid, judges, dataset) -> dict[str, float]:
    """Per-policy jury accuracy over all cases, using the same per-case rule."""
    n = len(dataset.cases)
    acc: dict[str, float] = {}
    for name, policy in POLICIES.items():
        if not n:
            acc[name] = 0.0
            continue
        correct = sum(
            _case_correct(
                _jury_flagged(grid, judges, case, policy),
                case.expected_output,
                _also_valid(case),
            )
            for case in dataset.cases
        )
        acc[name] = correct / n
    return acc


def run(
    clients: list | None = None,
    specs: list[JudgeSpec] | None = None,
    guidelines: Guidelines | None = None,
    dataset: Dataset | None = None,
) -> JuryEvalReport:
    """Run the jury meta-eval and compute per-judge accuracy, inter-judge kappa,
    per-policy jury accuracy, and jury-vs-best-single lift.

    - Offline path: inject ``clients`` (fakes or ``JudgeClient.from_model``);
      per-judge accuracy is computed from ``collect_grid`` (no model needed).
    - Real path (key-gated, NOT run in the dev env): pass ``specs``; available
      judges are built via ``JudgeClient.from_spec`` and each judge's accuracy /
      full ``MetaEvalReport`` come from ``meta_eval.run(model=<spec model>)``.
    - ``guidelines`` defaults to meta_eval's offline grounding-free object;
      ``dataset`` defaults to ``build_dataset()``. Accuracy is always scored over
      ALL ``dataset.cases`` -- the denominator is never shrunk.
    """
    if dataset is None:
        dataset = build_dataset()
    if guidelines is None:
        guidelines = _offline_guidelines()

    per_judge_report: dict[str, MetaEvalReport] = {}

    if clients is None:
        # Real path: build judges from specs (requires API keys at run time).
        if specs is None:
            raise ValueError("run() needs either `clients` (offline) or `specs` (real path)")
        clients = [JudgeClient.from_spec(s) for s in specs if s.available]
        if not clients:
            raise RuntimeError(
                "no available judges resolved from specs (missing API key/base_url?)"
            )
        for spec in specs:
            if spec.available:
                per_judge_report[spec.name] = meta_eval.run(
                    model=_model_ref(spec), guidelines=guidelines, dataset=dataset
                )

    grid = collect_grid(clients, dataset, guidelines)
    judges = [c.name for c in clients]

    per_judge_accuracy: dict[str, float] = {}
    for name in judges:
        if name in per_judge_report:
            per_judge_accuracy[name] = per_judge_report[name].accuracy
        else:
            per_judge_accuracy[name] = _score_grid(grid[name], dataset)

    jury_accuracy = _jury_accuracy(grid, judges, dataset)
    best_single = max(per_judge_accuracy.values()) if per_judge_accuracy else 0.0
    # No flooring: a negative lift is a real, reportable result.
    lift = {name: jury_accuracy[name] - best_single for name in jury_accuracy}

    return JuryEvalReport(
        per_judge_accuracy=per_judge_accuracy,
        per_judge_report=per_judge_report,
        inter_judge_kappa=_inter_judge_kappa(grid, judges, dataset),
        jury_accuracy=jury_accuracy,
        best_single_accuracy=best_single,
        lift=lift,
    )
