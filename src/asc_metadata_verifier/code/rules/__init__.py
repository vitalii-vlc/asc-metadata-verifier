"""Rule registry. Each cluster module exposes a `RULES: list[Rule]`; importing
this package assembles the global `REGISTRY`. Rules are pure: given a
`ProjectModel` + `ASTIndex`, return `CodeFinding`s and nothing else."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.models import CodeFinding


@runtime_checkable
class Rule(Protocol):
    id: str
    category: str
    guideline_ref: str
    severity: str  # "low" | "medium" | "high"
    interpretive: bool
    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]: ...


def _load_registry() -> list[Rule]:
    from asc_metadata_verifier.code.rules import (
        compliance,
        deprecated_api,
        privacy,
        security,
    )

    registry: list[Rule] = []
    for module in (privacy, deprecated_api, security, compliance):
        registry.extend(module.RULES)
    return registry


REGISTRY: list[Rule] = _load_registry()
