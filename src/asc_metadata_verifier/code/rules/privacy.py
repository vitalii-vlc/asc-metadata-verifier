"""Privacy & tracking rules (App Store Review Guideline 5.1.x).

False-negative note: symbol detection is presence-based (identifier appears in
the AST). Aliased/dynamically-constructed calls (e.g. NSClassFromString) are
NOT detected -- documented, curated coverage, not exhaustive."""

from __future__ import annotations

import re

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules.data.required_reason_apis import REQUIRED_REASON_APIS
from asc_metadata_verifier.models import CodeFinding

_USAGE_MAP = {
    "AVCaptureDevice": "NSCameraUsageDescription",
    "CLLocationManager": "NSLocationWhenInUseUsageDescription",
    "CNContactStore": "NSContactsUsageDescription",
    "PHPhotoLibrary": "NSPhotoLibraryUsageDescription",
    "AVAudioRecorder": "NSMicrophoneUsageDescription",
    "EKEventStore": "NSCalendarsUsageDescription",
    "HKHealthStore": "NSHealthShareUsageDescription",
}
_GENERIC_RE = re.compile(r"^\s*(we need|this app needs|required|allow access)\b", re.IGNORECASE)


def _all_symbols(asts: ASTIndex) -> dict[str, tuple[str, int]]:
    """symbol -> (file, line=1) for the first file that contains it, for evidence."""
    seen: dict[str, tuple[str, int]] = {}
    for path, ast in sorted(asts.items()):
        for sym in ast.symbols():
            seen.setdefault(sym, (path, 1))
    return seen


def _plist_has_key(project: ProjectModel, key: str) -> bool:
    return any(p.data and key in p.data for p in project.info_plists)


class IdfaWithoutAtt:
    id = "idfa-without-att"
    category = "privacy-tracking"
    guideline_ref = "5.1.2"
    severity = "high"
    interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        symbols = _all_symbols(asts)
        idfa = next(
            (s for s in ("ASIdentifierManager", "advertisingIdentifier") if s in symbols), None
        )
        if idfa is None:
            return []
        all_syms = set(symbols)
        has_att = "ATTrackingManager" in all_syms
        has_str = _plist_has_key(project, "NSUserTrackingUsageDescription")
        if has_att and has_str:
            return []
        file, line = symbols[idfa]
        return [CodeFinding(
            rule_id=self.id, category=self.category, severity=self.severity,
            guideline_ref=self.guideline_ref, file=file, line=line, symbol=idfa, evidence=idfa,
            detail="IDFA is accessed without an ATT prompt and/or NSUserTrackingUsageDescription",
            suggested_fix="Call ATTrackingManager.requestTrackingAuthorization and add "
                          "NSUserTrackingUsageDescription")]


class MissingUsageString:
    id = "missing-usage-string"
    category = "privacy-permissions"
    guideline_ref = "5.1.1"
    severity = "high"
    interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        symbols = _all_symbols(asts)
        out: list[CodeFinding] = []
        for sym, key in _USAGE_MAP.items():
            if sym in symbols and not _plist_has_key(project, key):
                file, line = symbols[sym]
                out.append(CodeFinding(
                    rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=file, line=line,
                    symbol=sym, evidence=sym,
                    detail=f"{sym} used but {key} is missing from Info.plist",
                    suggested_fix=f"Add a {key} string describing why the app needs this."))
        return out


class RequiredReasonApiUndeclared:
    id = "required-reason-api-undeclared"
    category = "privacy-manifest"
    guideline_ref = "Apple privacy-manifest policy"
    severity = "high"
    interpretive = False

    def _declared(self, project: ProjectModel) -> set[str]:
        declared: set[str] = set()
        for pm in project.privacy_manifests:
            for entry in (pm.data or {}).get("NSPrivacyAccessedAPITypes", []) or []:
                if isinstance(entry, dict) and entry.get("NSPrivacyAccessedAPIType"):
                    declared.add(entry["NSPrivacyAccessedAPIType"])
        return declared

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        symbols = _all_symbols(asts)
        declared = self._declared(project)
        out: list[CodeFinding] = []
        seen_categories: set[str] = set()
        for sym, category in REQUIRED_REASON_APIS.items():
            if sym in symbols and category not in declared and category not in seen_categories:
                seen_categories.add(category)
                file, line = symbols[sym]
                out.append(CodeFinding(
                    rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=file, line=line,
                    symbol=sym, evidence=sym,
                    detail=f"{sym} requires declaring {category} in PrivacyInfo.xcprivacy",
                    suggested_fix=f"Add {category} with an approved reason to "
                                  "PrivacyInfo.xcprivacy."))
        return out


class BoilerplateUsageString:
    id = "boilerplate-usage-string"
    category = "privacy-permissions"
    guideline_ref = "5.1.1"
    severity = "medium"
    interpretive = True

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for plist in project.info_plists:
            for key, value in sorted((plist.data or {}).items()):
                if not key.endswith("UsageDescription") or not isinstance(value, str):
                    continue
                if value.strip() == "" or len(value.strip()) < 12 or _GENERIC_RE.match(value):
                    out.append(CodeFinding(
                        rule_id=self.id, category=self.category, severity=self.severity,
                        guideline_ref=self.guideline_ref, file=plist.path, line=None, symbol=key,
                        evidence=value, detail=f"{key} looks too generic/short to satisfy 5.1.1",
                        suggested_fix="Explain specifically why the app needs this data."))
        return out


RULES = [
    IdfaWithoutAtt(),
    MissingUsageString(),
    RequiredReasonApiUndeclared(),
    BoilerplateUsageString(),
]
