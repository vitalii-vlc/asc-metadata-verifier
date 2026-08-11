"""Security / ATS rules (App Store Review Guideline 2.5.2)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.models import CodeFinding

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class AtsArbitraryLoads:
    id = "ats-arbitrary-loads"
    category = "security-ats"
    guideline_ref = "2.5.2"
    severity = "medium"
    interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for plist in project.info_plists:
            ats = (plist.data or {}).get("NSAppTransportSecurity")
            if isinstance(ats, dict) and ats.get("NSAllowsArbitraryLoads") is True:
                out.append(CodeFinding(
                    rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=plist.path, line=None,
                    symbol="NSAllowsArbitraryLoads", evidence="NSAllowsArbitraryLoads=true",
                    detail="ATS disabled globally; Apple requires justification (2.5.2)",
                    suggested_fix="Remove NSAllowsArbitraryLoads or scope exceptions per-domain."))
        return out


class InsecureHttpEndpoint:
    id = "insecure-http-endpoint"
    category = "security-ats"
    guideline_ref = "2.5.2"
    severity = "low"
    interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for _path, ast in sorted(asts.items()):
            for lit in ast.string_literals():
                if not re.match(r"^http://", lit.value):
                    continue
                host = urlparse(lit.value).hostname or ""
                if host in _LOCAL_HOSTS:
                    continue
                out.append(CodeFinding(
                    rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=lit.file, line=lit.line, symbol=None,
                    evidence=lit.value, detail="Insecure http:// endpoint in source (2.5.2)",
                    suggested_fix="Use https:// for network endpoints."))
        return out


RULES = [AtsArbitraryLoads(), InsecureHttpEndpoint()]
