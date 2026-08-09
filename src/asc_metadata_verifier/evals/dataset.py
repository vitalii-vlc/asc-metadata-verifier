"""Load the golden JSONL into a pydantic-evals ``Dataset``.

One ``Case`` per JSONL line (so ``len(dataset.cases)`` equals the number of
labeled rows). ``inputs`` carry what the meta-eval task needs to run the judge
(text, locale, field, and the labeled dimension-under-test); ``expected_output``
carries the ground-truth label (dimension + verdict) that the meta-eval scores
against. ``metadata`` keeps the raw ``source_note`` rationale plus the
``also_valid_dimensions`` MULTI-LABEL ground truth (see below) for auditing and
scoring.

Multi-label ground truth: real metadata can genuinely trip more than one
dimension (competitor brand names are both keyword-stuffing AND a third-party
trademark; "cheaper ... on our website" is both an off-platform link AND a price
term). ``expected_dimension`` is the single PRIMARY label; the optional
``also_valid_dimensions`` list names OTHER dimensions genuinely present, so that
a judge flag on them is an accepted secondary detection rather than a false
positive. Single-label ground truth would falsely penalize a correct judge.

Honesty note: the labels in ``golden/*.jsonl`` ARE the ground truth. Every row is
a realistic SYNTHETIC example grounded in the 8 rubric dimensions and the real
App Store Review Guidelines 2.3 / 5.2 categories; ``source_note`` states the
category rationale rather than claiming a verbatim quote from a real app.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel
from pydantic_evals import Case, Dataset

from asc_metadata_verifier.judge.rubric import DIMENSIONS

GOLDEN_DIR = Path(__file__).parent / "golden"

_DIMENSION_IDS = {d.id for d in DIMENSIONS}
_VALID_DIMENSIONS = _DIMENSION_IDS | {"none"}
_VALID_VERDICTS = {"pass", "warn", "fail"}
_REQUIRED_KEYS = {
    "text",
    "locale",
    "field",
    "expected_dimension",
    "expected_verdict",
    "source_note",
}


class CaseInputs(BaseModel):
    """Everything the meta-eval task needs to judge one golden case.

    ``dimension`` is the labeled dimension-under-test (or ``"none"`` for a clean
    control). The meta-eval runs the FULL 8-dimension grid per case to capture
    cross-dimension false positives, so the task does not rely on ``dimension``
    to decide what to run; it is carried for traceability only.
    """

    text: str
    locale: str
    field: str
    dimension: str


class CaseExpected(BaseModel):
    """Ground-truth label for one golden case."""

    expected_dimension: str
    expected_verdict: str


def _golden_files() -> list[Path]:
    return sorted(GOLDEN_DIR.glob("*.jsonl"))


def _iter_rows() -> list[dict]:
    rows: list[dict] = []
    for path in _golden_files():
        with path.open(encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                    raise ValueError(f"{path.name}:{lineno}: invalid JSON: {exc}") from exc
                _validate_row(row, path.name, lineno)
                rows.append(row)
    return rows


def _validate_row(row: dict, filename: str, lineno: int) -> None:
    missing = _REQUIRED_KEYS - row.keys()
    if missing:
        raise ValueError(f"{filename}:{lineno}: missing keys {sorted(missing)}")
    dim = row["expected_dimension"]
    verdict = row["expected_verdict"]
    if dim not in _VALID_DIMENSIONS:
        raise ValueError(f"{filename}:{lineno}: bad expected_dimension {dim!r}")
    if verdict not in _VALID_VERDICTS:
        raise ValueError(f"{filename}:{lineno}: bad expected_verdict {verdict!r}")
    # Label coherence: a clean control passes; a positive case is flagged.
    if dim == "none" and verdict != "pass":
        raise ValueError(f"{filename}:{lineno}: 'none' case must be pass, got {verdict!r}")
    if dim != "none" and verdict not in {"warn", "fail"}:
        raise ValueError(
            f"{filename}:{lineno}: positive case ({dim}) must be warn/fail, got {verdict!r}"
        )
    if not str(row["text"]).strip():
        raise ValueError(f"{filename}:{lineno}: empty text")
    # Multi-label ground truth (optional): each entry must be a real dimension,
    # distinct from the primary label, and not repeated.
    also_valid = row.get("also_valid_dimensions", [])
    if not isinstance(also_valid, list):
        raise ValueError(f"{filename}:{lineno}: also_valid_dimensions must be a list")
    if len(set(also_valid)) != len(also_valid):
        raise ValueError(f"{filename}:{lineno}: duplicate also_valid_dimensions {also_valid}")
    for entry in also_valid:
        if entry not in _DIMENSION_IDS:
            raise ValueError(f"{filename}:{lineno}: bad also_valid_dimension {entry!r}")
        if entry == dim:
            raise ValueError(
                f"{filename}:{lineno}: also_valid_dimension duplicates expected_dimension {entry!r}"
            )


def count_golden_lines() -> int:
    """Number of labeled rows across all ``golden/*.jsonl`` files."""
    return len(_iter_rows())


def build_dataset() -> Dataset[CaseInputs, CaseExpected, dict]:
    """Load ``golden/*.jsonl`` into a pydantic-evals ``Dataset``.

    One ``Case`` per JSONL line. No evaluators are attached: the meta-eval
    computes agreement statistics itself from the collected per-case outputs
    (see ``meta_eval.run``), which lets it run the full dimension x case grid.
    """
    cases: list[Case[CaseInputs, CaseExpected, dict]] = []
    for index, row in enumerate(_iter_rows()):
        inputs = CaseInputs(
            text=row["text"],
            locale=row["locale"],
            field=row["field"],
            dimension=row["expected_dimension"],
        )
        expected = CaseExpected(
            expected_dimension=row["expected_dimension"],
            expected_verdict=row["expected_verdict"],
        )
        name = f"{index:02d}-{row['expected_dimension']}"
        cases.append(
            Case(
                name=name,
                inputs=inputs,
                expected_output=expected,
                metadata={
                    "source_note": row["source_note"],
                    "field": row["field"],
                    "also_valid_dimensions": list(row.get("also_valid_dimensions", [])),
                },
            )
        )
    return Dataset(name="asc-golden", cases=cases)
