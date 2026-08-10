"""Tests for privacy/tracking rules (5.1.x) — v2 sub-project C, Task 5."""

from asc_metadata_verifier.code.project import PlistArtifact, ProjectModel, SourceFile
from asc_metadata_verifier.code.rules.privacy import RULES


class _AST:
    def __init__(self, file, syms):
        self.file = file
        self._s = syms

    def symbols(self):
        return self._s

    def imports(self):
        return set()

    def calls(self, name):
        return []

    def string_literals(self):
        return []


def _run(rule_id, project, asts):
    rule = next(r for r in RULES if r.id == rule_id)
    return rule.check(project, asts)


def test_idfa_without_att_flags():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
                        info_plists=[PlistArtifact(path="Info.plist", data={})])
    asts = {"A.swift": _AST("A.swift", {"ASIdentifierManager"})}
    out = _run("idfa-without-att", proj, asts)
    assert len(out) == 1 and out[0].severity == "high" and out[0].guideline_ref == "5.1.2"


def test_idfa_with_att_and_usage_string_is_clean():
    proj = ProjectModel(
        root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
        info_plists=[PlistArtifact(path="Info.plist",
                                   data={"NSUserTrackingUsageDescription": "To measure ads."})])
    asts = {"A.swift": _AST("A.swift", {"ASIdentifierManager", "ATTrackingManager"})}
    assert _run("idfa-without-att", proj, asts) == []


def test_missing_usage_string_flags_camera():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
                        info_plists=[PlistArtifact(path="Info.plist", data={})])
    asts = {"A.swift": _AST("A.swift", {"AVCaptureDevice"})}
    out = _run("missing-usage-string", proj, asts)
    assert len(out) == 1 and "NSCameraUsageDescription" in out[0].detail


def test_missing_usage_string_clean_when_declared():
    proj = ProjectModel(
        root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
        info_plists=[PlistArtifact(path="Info.plist",
                                   data={"NSCameraUsageDescription": "For scanning."})])
    asts = {"A.swift": _AST("A.swift", {"AVCaptureDevice"})}
    assert _run("missing-usage-string", proj, asts) == []


def test_required_reason_api_undeclared_flags():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")])
    asts = {"A.swift": _AST("A.swift", {"UserDefaults"})}
    out = _run("required-reason-api-undeclared", proj, asts)
    assert len(out) >= 1 and out[0].severity == "high"


def test_required_reason_api_declared_is_clean():
    proj = ProjectModel(
        root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
        privacy_manifests=[PlistArtifact(
            path="PrivacyInfo.xcprivacy",
            data={"NSPrivacyAccessedAPITypes": [
                {"NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults"}]})])
    asts = {"A.swift": _AST("A.swift", {"UserDefaults"})}
    assert _run("required-reason-api-undeclared", proj, asts) == []


def test_boilerplate_usage_string_flags_and_is_interpretive():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(
        path="Info.plist", data={"NSCameraUsageDescription": "We need access"})])
    out = _run("boilerplate-usage-string", proj, {})
    assert len(out) == 1 and out[0].severity == "medium"
    rule = next(r for r in RULES if r.id == "boilerplate-usage-string")
    assert rule.interpretive is True
