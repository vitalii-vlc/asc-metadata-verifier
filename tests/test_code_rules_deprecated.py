"""Tests for deprecated/private-API rules (2.5.x) — v2 sub-project C, Task 6."""

from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules.deprecated_api import RULES


class _AST:
    def __init__(self, file, syms):
        self.file = file
        self._s = syms

    def symbols(self):
        return self._s

    def imports(self):
        return set()

    def calls(self, n):
        return []

    def string_literals(self):
        return []


def _run(rid, asts):
    return next(r for r in RULES if r.id == rid).check(ProjectModel(root="/p"), asts)


def test_uiwebview_flagged_per_file():
    out = _run("uiwebview-usage", {"A.swift": _AST("A.swift", {"UIWebView"})})
    assert len(out) == 1 and out[0].severity == "high" and out[0].file == "A.swift"


def test_uiwebview_clean_when_absent():
    assert _run("uiwebview-usage", {"A.swift": _AST("A.swift", {"WKWebView"})}) == []


def test_private_api_symbol_flagged():
    out = _run("private-api-symbol", {"A.swift": _AST("A.swift", {"LSApplicationWorkspace"})})
    assert len(out) == 1 and out[0].guideline_ref == "2.5.1"
