"""Build the data-collection profile a privacy POLICY should disclose, from C's
findings. Deliberately policy-relevant categories only -- NOT required-reason
manifest categories (those belong to PrivacyInfo.xcprivacy, not the prose)."""

from __future__ import annotations

from pydantic import BaseModel

from asc_metadata_verifier.models import CodeFinding

# usage-string symbol / NS*UsageDescription key -> human data category
_SYMBOL_CATEGORY = {
    "AVCaptureDevice": "camera",
    "NSCameraUsageDescription": "camera",
    "CLLocationManager": "location",
    "NSLocationWhenInUseUsageDescription": "location",
    "CNContactStore": "contacts",
    "NSContactsUsageDescription": "contacts",
    "PHPhotoLibrary": "photos",
    "NSPhotoLibraryUsageDescription": "photos",
    "AVAudioRecorder": "microphone",
    "NSMicrophoneUsageDescription": "microphone",
    "EKEventStore": "calendar",
    "NSCalendarsUsageDescription": "calendar",
    "HKHealthStore": "health",
    "NSHealthShareUsageDescription": "health",
}
_USAGE_RULES = {"missing-usage-string", "boilerplate-usage-string"}


class DataCollectionProfile(BaseModel):
    categories: list[str]


def build_profile(code_findings: list[CodeFinding]) -> DataCollectionProfile:
    cats: set[str] = set()
    for f in code_findings:
        if f.rule_id in _USAGE_RULES and f.symbol in _SYMBOL_CATEGORY:
            cats.add(_SYMBOL_CATEGORY[f.symbol])
        elif f.rule_id == "idfa-without-att":
            cats.add("advertising identifier")
    return DataCollectionProfile(categories=sorted(cats))
