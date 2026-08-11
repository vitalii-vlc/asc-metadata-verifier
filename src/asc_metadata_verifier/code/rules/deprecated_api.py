"""Deprecated / private API rules (App Store Review Guideline 2.5.x).

False-negative note: detection is presence-based over a curated symbol set;
the private-API denylist is a high-signal subset, not Apple's full list."""

from __future__ import annotations

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules.data.private_api_symbols import PRIVATE_API_SYMBOLS
from asc_metadata_verifier.models import CodeFinding


class UIWebViewUsage:
    id = "uiwebview-usage"
    category = "deprecated-api"
    guideline_ref = "2.5.x"
    severity = "high"
    interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for path, ast in sorted(asts.items()):
            if "UIWebView" in ast.symbols():
                out.append(CodeFinding(
                    rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=path, line=1, symbol="UIWebView",
                    evidence="UIWebView", detail="UIWebView is deprecated and rejected since 2020",
                    suggested_fix="Replace UIWebView with WKWebView."))
        return out


class PrivateApiSymbol:
    id = "private-api-symbol"
    category = "private-api"
    guideline_ref = "2.5.1"
    severity = "high"
    interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for path, ast in sorted(asts.items()):
            for sym in sorted(ast.symbols() & PRIVATE_API_SYMBOLS):
                out.append(CodeFinding(
                    rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=path, line=1, symbol=sym, evidence=sym,
                    detail=f"{sym} is a private/undocumented API (2.5.1)",
                    suggested_fix="Use a public API; private symbols draw rejection."))
        return out


RULES = [UIWebViewUsage(), PrivateApiSymbol()]
