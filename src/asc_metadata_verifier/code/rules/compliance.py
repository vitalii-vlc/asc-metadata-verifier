"""Compliance & consistency rules (export compliance, URL-scheme queries)."""

from __future__ import annotations

import re

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.models import CodeFinding

# Requires the "://" separator: a bare "word:" prefix matches ordinary prose
# such as a log tag ("AudioService: ready") or a test name ("RULE: ..."), which
# are not URLs and must not be reported as undeclared query schemes.
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://")
_COMMON_SCHEMES = {"http", "https", "file", "mailto", "tel"}


class EncryptionExportUndeclared:
    id = "encryption-export-undeclared"
    category = "compliance"
    guideline_ref = "export compliance"
    severity = "medium"
    interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        if any(p.data and "ITSAppUsesNonExemptEncryption" in p.data for p in project.info_plists):
            return []
        if not project.info_plists:
            return []  # no Info.plist parsed -> nothing factual to point at
        target = project.info_plists[0].path
        return [CodeFinding(
            rule_id=self.id, category=self.category, severity=self.severity,
            guideline_ref=self.guideline_ref, file=target, line=None,
            symbol="ITSAppUsesNonExemptEncryption", evidence="(absent)",
            detail="ITSAppUsesNonExemptEncryption is not declared; submission will prompt/stall",
            suggested_fix="Add ITSAppUsesNonExemptEncryption (true/false) to Info.plist.")]


class CanOpenUrlUndeclaredScheme:
    id = "canopenurl-undeclared-scheme"
    category = "compliance"
    guideline_ref = "2.5.x"
    severity = "low"
    interpretive = False

    def _declared(self, project: ProjectModel) -> set[str]:
        out: set[str] = set()
        for p in project.info_plists:
            for s in (p.data or {}).get("LSApplicationQueriesSchemes", []) or []:
                if isinstance(s, str):
                    out.add(s.lower())
        return out

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        declared = self._declared(project)
        out: list[CodeFinding] = []
        for _path, ast in sorted(asts.items()):
            for lit in ast.string_literals():
                m = _SCHEME_RE.match(lit.value)
                if not m:
                    continue
                scheme = m.group(1).lower()
                if scheme in _COMMON_SCHEMES or scheme in declared:
                    continue
                out.append(CodeFinding(
                    rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=lit.file, line=lit.line, symbol=scheme,
                    evidence=lit.value,
                    detail=f"URL scheme '{scheme}' not in LSApplicationQueriesSchemes",
                    suggested_fix=f"Add '{scheme}' to LSApplicationQueriesSchemes if you "
                                  "query it."))
        return out


RULES = [EncryptionExportUndeclared(), CanOpenUrlUndeclaredScheme()]
