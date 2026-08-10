"""Tests for the rule engine core + analyzer orchestrator (Task 4).

Uses a fake parser/AST so no `[code]` extra is needed. The real REGISTRY is
asserted in tests/test_code_registry.py once the cluster modules land (Task 7);
at Task 4 the guarded registry may be empty by design."""

from asc_metadata_verifier.code import rules as rules_mod
from asc_metadata_verifier.code.analyzer import analyze, build_code_report
from asc_metadata_verifier.code.project import ProjectModel, SourceFile
from asc_metadata_verifier.models import CodeFinding


class _FakeAST:
    def __init__(self, file):
        self.file = file

    def symbols(self):
        return {"UIWebView"}

    def imports(self):
        return set()

    def calls(self, name):
        return []

    def string_literals(self):
        return []


class _FakeParser:
    backend_name = "fake"

    def available(self):
        return True

    def parse(self, source):
        return _FakeAST(source.path)


def test_registry_is_a_list():
    assert isinstance(rules_mod.REGISTRY, list)


def test_analyze_runs_rules_and_sorts(monkeypatch):
    class R:
        id = "x"
        category = "c"
        guideline_ref = "2.5.x"
        severity = "high"
        interpretive = False

        def check(self, project, asts):
            return [
                CodeFinding(rule_id="x", category="c", severity="high", guideline_ref="2.5.x",
                            file="B.swift", line=9, evidence="e", detail="d"),
                CodeFinding(rule_id="x", category="c", severity="high", guideline_ref="2.5.x",
                            file="A.swift", line=1, evidence="e", detail="d"),
            ]

    monkeypatch.setattr(rules_mod, "REGISTRY", [R()])
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")])
    findings, asts = analyze(proj, _FakeParser())
    assert [f.file for f in findings] == ["A.swift", "B.swift"]  # sorted by (file, line, rule_id)


def test_build_code_report_status_from_severity():
    hi = CodeFinding(rule_id="x", category="c", severity="high", guideline_ref="2.5",
                     file="A.swift", line=1, evidence="e", detail="d")
    rep = build_code_report([hi], analyzed_files=1, backend="tree-sitter")
    assert rep.status == "BLOCK" and rep.analyzed_files == 1 and rep.parser_backend == "tree-sitter"
