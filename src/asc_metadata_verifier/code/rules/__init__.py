"""Rule registry. Each cluster module exposes a `RULES: list[Rule]`; importing
this package assembles the global `REGISTRY`. Rules are pure: given a
`ProjectModel` + `ASTIndex`, return `CodeFinding`s and nothing else.

Transitional guard: until the cluster modules (privacy/deprecated_api/security/
compliance) land in Tasks 5-7, `_load_registry` swallows the ImportError and
REGISTRY is empty. Task 7 removes the guard and a registry test asserts the
full set."""

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
    registry: list[Rule] = []
    try:
        from asc_metadata_verifier.code.rules import (
            compliance,
            deprecated_api,
            privacy,
            security,
        )

        for module in (privacy, deprecated_api, security, compliance):
            registry.extend(module.RULES)
    except ImportError:
        pass  # cluster modules land in Tasks 5-7; Task 7 removes this guard.
    return registry


REGISTRY: list[Rule] = _load_registry()
