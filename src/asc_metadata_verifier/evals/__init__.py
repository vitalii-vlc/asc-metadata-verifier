"""Golden dataset + pydantic-evals judge meta-eval (Task 13).

This package holds the eval-science substance of the project:

- ``golden/*.jsonl`` : a curated, honestly-labeled dataset of realistic
  synthetic App Store metadata snippets, one per line, covering all 8 rubric
  dimensions plus clean controls designed to stress the judge.
- ``dataset``        : loads the golden set into a ``pydantic_evals.Dataset``.
- ``meta_eval``      : runs the judge over the golden set and computes
  judge-vs-ground-truth agreement (per-dimension precision/recall, accuracy,
  and a failure taxonomy).
"""

from asc_metadata_verifier.evals.dataset import (
    CaseExpected,
    CaseInputs,
    build_dataset,
    count_golden_lines,
)
from asc_metadata_verifier.evals.meta_eval import MetaEvalReport, run

__all__ = (
    "CaseExpected",
    "CaseInputs",
    "MetaEvalReport",
    "build_dataset",
    "count_golden_lines",
    "run",
)
