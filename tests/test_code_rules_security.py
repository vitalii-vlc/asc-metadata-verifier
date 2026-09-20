"""Tests for security (2.5.2) + compliance rules — v2 sub-project C, Task 7."""

from asc_metadata_verifier.code.parser import StringLit
from asc_metadata_verifier.code.project import PlistArtifact, ProjectModel
from asc_metadata_verifier.code.rules.compliance import RULES as COMP
from asc_metadata_verifier.code.rules.security import RULES as SEC


class _AST:
    def __init__(self, file, strings):
        self.file = file
        self._str = strings

    def symbols(self):
        return set()

    def imports(self):
        return set()

    def calls(self, n):
        return []

    def string_literals(self):
        return self._str


def _run(rules, rid, project, asts):
    return next(r for r in rules if r.id == rid).check(project, asts)


def test_ats_arbitrary_loads_flagged():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(
        path="Info.plist", data={"NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True}})])
    out = _run(SEC, "ats-arbitrary-loads", proj, {})
    assert len(out) == 1 and out[0].severity == "medium"


def test_insecure_http_endpoint_flagged_not_localhost():
    asts = {"A.swift": _AST("A.swift", [
        StringLit(value="http://api.example.com", file="A.swift", line=4),
        StringLit(value="http://localhost:8080", file="A.swift", line=5)])}
    out = _run(SEC, "insecure-http-endpoint", ProjectModel(root="/p"), asts)
    assert len(out) == 1 and out[0].line == 4


def test_encryption_export_undeclared_flagged_when_absent():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(
        path="Info.plist", data={"CFBundleName": "x"})])
    assert len(_run(COMP, "encryption-export-undeclared", proj, {})) == 1


def test_encryption_export_clean_when_present():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(
        path="Info.plist", data={"ITSAppUsesNonExemptEncryption": False})])
    assert _run(COMP, "encryption-export-undeclared", proj, {}) == []


def test_canopenurl_undeclared_scheme_flagged():
    asts = {"A.swift": _AST("A.swift",
                            [StringLit(value="whatsapp://send", file="A.swift", line=2)])}
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(
        path="Info.plist", data={"LSApplicationQueriesSchemes": ["tel"]})])
    out = _run(COMP, "canopenurl-undeclared-scheme", proj, asts)
    assert len(out) == 1 and out[0].symbol == "whatsapp"


def test_canopenurl_ignores_non_url_literals_with_a_colon():
    # A log prefix ("AudioService: ready") or a test description ("RULE: ...")
    # is not a URL; only a literal carrying a scheme separator is.
    asts = {"A.swift": _AST("A.swift", [
        StringLit(value="AudioService: audio session unavailable", file="A.swift", line=3),
        StringLit(value="RULE: launch catch-up is silent.", file="A.swift", line=4),
        StringLit(value="Tazik24: Той самий гараж", file="A.swift", line=5),
        StringLit(value="instagram://user?username=x", file="A.swift", line=6)])}
    out = _run(COMP, "canopenurl-undeclared-scheme", ProjectModel(root="/p"), asts)
    assert [(f.symbol, f.line) for f in out] == [("instagram", 6)]
