"""Orchestrator: parse each source once into an ASTIndex, run every registered
rule, return sorted CodeFindings. Deterministic: identical input -> identical
ordered output. No LLM here (that is code/jury.py).

`rules.REGISTRY` is referenced via the module attribute (not a `from ... import
REGISTRY` binding) so tests can monkeypatch it and the analyzer sees the swap."""

from __future__ import annotations

from asc_metadata_verifier.code import rules
from asc_metadata_verifier.code.parser import ASTIndex, SourceParser
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.gate import evaluate
from asc_metadata_verifier.models import CodeFinding, CodeReport


def analyze(project: ProjectModel, parser: SourceParser) -> tuple[list[CodeFinding], ASTIndex]:
    asts: ASTIndex = {sf.path: parser.parse(sf) for sf in project.sources}
    findings: list[CodeFinding] = []
    for rule in rules.REGISTRY:
        findings.extend(rule.check(project, asts))
    findings.sort(key=lambda f: (f.file, f.line or 0, f.rule_id))
    return findings, asts


def build_code_report(
    findings: list[CodeFinding],
    analyzed_files: int,
    backend: str,
    *,
    fail_on: str = "fail",
    jury_used: bool = False,
) -> CodeReport:
    status = evaluate([], [], fail_on=fail_on, code_findings=findings).status
    return CodeReport(
        status=status,
        findings=findings,
        analyzed_files=analyzed_files,
        parser_backend=backend,
        jury_used=jury_used,
    )
