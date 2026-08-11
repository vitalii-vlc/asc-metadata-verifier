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


JudgeStatus = Literal["voted", "abstained", "error", "not_applicable"]


class JudgeVote(BaseModel):
    """One judge's outcome for one unit. `verdict` is set iff status == 'voted';
    `error` iff status == 'error'. abstained/error/not_applicable are excluded
    from the consensus tally but retained for the honesty record."""

    judge: str
    status: JudgeStatus
    verdict: RubricVerdict | None = None
    error: str | None = None
    latency_ms: float | None = None


class PanelVerdict(BaseModel):
    """Every judge's vote on one (locale, dimension) [text] or (screenshot,
    dimension) [vision] unit, plus the aggregated consensus the gate consumes.
    `field` is descriptive (copied from the consensus), not a grouping key —
    units are keyed by (locale, dimension)."""

    locale: str
    dimension: str
    field: str
    votes: list[JudgeVote]
    consensus: RubricVerdict
    policy: str
    agreement: float | None = None


class CodeFinding(BaseModel):
    """One static (or jury-adjudicated) code/config rejection-risk finding.

    Anchored to a real `file` (+ `line` when the token has one) and an
    `evidence` quote a human can open and verify. `source="jury"` items carry
    the full `panel` vote record -- LLM judgment is never presented as a
    deterministic fact."""

    rule_id: str
    category: str
    severity: Literal["low", "medium", "high"]
    guideline_ref: str
    file: str
    line: int | None = None
    symbol: str | None = None
    evidence: str
    detail: str
    suggested_fix: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: Literal["static", "jury"] = "static"
    panel: PanelVerdict | None = None


class CodeReport(BaseModel):
    """Result of a standalone `asc-verify code <path>` run."""

    status: Literal["PASS", "WARN", "BLOCK"]
    findings: list[CodeFinding] = Field(default_factory=list)
    analyzed_files: int = 0
    parser_backend: str = ""
    jury_used: bool = False


class PageFinding(BaseModel):
    """One privacy/support/marketing page rejection-risk finding, anchored to a
    real URL. `source="jury"` items carry the full `panel` vote record."""

    page_type: Literal["privacy", "support", "marketing"]
    url: str
    rule_id: str
    category: str
    severity: Literal["low", "medium", "high"]
    guideline_ref: str
    evidence: str
    detail: str
    suggested_fix: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: Literal["static", "jury"] = "static"
    panel: PanelVerdict | None = None


class PagesReport(BaseModel):
    """Result of a standalone `asc-verify pages <metadata>` run."""

    status: Literal["PASS", "WARN", "BLOCK"]
    findings: list[PageFinding] = Field(default_factory=list)
    pages_checked: int = 0
    jury_used: bool = False


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
    panels: list[PanelVerdict] = Field(default_factory=list)
    code_findings: list[CodeFinding] = Field(default_factory=list)
    page_findings: list[PageFinding] = Field(default_factory=list)
