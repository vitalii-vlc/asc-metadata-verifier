from typing import Literal

from pydantic import BaseModel, Field


class RubricVerdict(BaseModel):
    dimension: str
    verdict: Literal["pass", "warn", "fail"]
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    offending_quote: str | None = None
    guideline_ref: str | None = None
    suggested_fix: str | None = None
    locale: str
    field: str


class LocaleMetadata(BaseModel):
    locale: str
    app_name: str | None = None
    subtitle: str | None = None
    promotional_text: str | None = None
    keywords: str | None = None
    description: str | None = None
    whats_new: str | None = None
    support_url: str | None = None
    marketing_url: str | None = None
    privacy_url: str | None = None


class Screenshot(BaseModel):
    locale: str
    path: str
    display_type: str | None = None


class AppMetadata(BaseModel):
    app_id: str | None = None
    primary_locale: str | None = None
    locales: list[LocaleMetadata] = Field(default_factory=list)
    screenshots: list[Screenshot] = Field(default_factory=list)


class DeterministicFinding(BaseModel):
    locale: str
    field: str
    kind: str
    detail: str


class GateReport(BaseModel):
    status: Literal["PASS", "WARN", "BLOCK"]
    verdicts: list[RubricVerdict] = Field(default_factory=list)
    deterministic_findings: list[DeterministicFinding] = Field(default_factory=list)
    guidelines_available: bool
