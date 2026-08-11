# Pages Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an additive, opt-in `pages` capability that fetches the app's declared privacy/support/marketing URLs (bounded, SSRF-guarded), runs deterministic reachability checks, and — opt-in jury — judges per-page guideline compliance plus the privacy-policy↔code cross-reference, folding findings into the same PASS/WARN/BLOCK gate.

**Architecture:** New `pages/` package: a `PageFetcher` (`HttpPageFetcher` with SSRF guard + caps; `LocalPageFetcher` for offline/tests) → `content.py` HTML→text → deterministic `checks.py` reachability → an opt-in `PageJury` (reuses A's `JudgeSpec`/consensus/`PanelVerdict`) judging adequacy and cross-referencing a `DataCollectionProfile` built from C's `CodeFinding`s → `analyzer.py` orchestrator. CLI gains `asc-verify pages` and `verify --pages`.

**Tech Stack:** Python 3.11+ (uv) · pydantic v2 · typer · **httpx (already a core dep — no new core dep)** · stdlib `ipaddress`/`socket`/`urllib.parse` (SSRF guard) · reuses C's `_analyze_project`, A's `judge/` panel, and `run_verify(dry_run=True)` for metadata ingest.

## Global Constraints

- **Additive / backward compatible (hard):** with no `pages` command and no `--pages` flag, behavior is byte-identical to today; `verify`/`code`/`history`/`diff`/`similar` and bare `asc-verify <path>` pass unchanged, do no extra I/O, and pull **zero new core dependencies** (httpx already core).
- **Opt-in network (honest):** `pages` hits the network by design (fetches live pages); `--pages-dir` gives a fully offline path. The whole test suite runs offline via an injected `LocalPageFetcher` / monkeypatched resolver / `httpx.MockTransport`.
- **Never fabricate:** a fetch failure → factual `unreachable`/`empty`, never invented content. `privacy-code-mismatch` is raised only by the jury from real fetched text, tagged `source="jury"` with votes. No `--code` / jury-off → those checks simply don't run.
- **SSRF guard (hard):** http(s) only; refuse a resolved host IP that is private/loopback/link-local/reserved; follow redirects manually, re-validating each hop (cap 5); connect/read timeout (10s) + response-size cap (2 MB, streamed). Documented residual: resolve-then-check, so DNS-rebinding is not hardened.
- **Curated / bounded:** the profile covers only policy-relevant categories (camera/location/contacts/photos/mic/calendar/health + advertising identifier), **not** required-reason manifest categories.
- **Severity → gate level:** `high` → block-worthy; `medium`/`low` → warn-worthy (mirrors `_code_level`/`_DETERMINISTIC_LEVEL`).
- **Secrets by reference:** jury mode reuses the env-var-ref `JudgeSpec` config; no key material in output/errors.
- **Style:** ruff clean (`E,F,I,UP,B`, line-length 100). `pytest` offline.

### Resolved during planning (empirical)

`limits.REQUIRED_FIELDS == {"app_name","description","keywords"}` — `privacy_url`/`support_url` are **not** in it, so `run_deterministic`'s `missing_required` never covers them. Therefore `privacy-policy-missing` (Task 6) does **not** duplicate the metadata layer; D owns it cleanly.

---

## Shared interfaces (defined once; tasks reference these exact names)

```python
# models.py additions
class PageFinding(BaseModel):
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
    status: Literal["PASS", "WARN", "BLOCK"]
    findings: list[PageFinding] = Field(default_factory=list)
    pages_checked: int = 0
    jury_used: bool = False
# GateReport gains:  page_findings: list[PageFinding] = Field(default_factory=list)

# pages/content.py
def html_to_text(html: str) -> str: ...

# pages/fetch.py
class FetchedPage(BaseModel):
    url: str
    final_url: str | None = None
    status: int | None = None
    ok: bool = False
    text: str | None = None
    error: str | None = None
class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...
class LocalPageFetcher:  # __init__(self, pages: dict[str, str])
    def fetch(self, url: str) -> FetchedPage: ...
class HttpPageFetcher:   # __init__(self, client=None, *, timeout=10.0, max_bytes=2_000_000, max_redirects=5)
    def fetch(self, url: str) -> FetchedPage: ...
# module-level, monkeypatchable: _resolve(host) -> list[str]; _ip_blocked(ip) -> bool; _host_safe(host) -> bool

# pages/profile.py
class DataCollectionProfile(BaseModel):
    categories: list[str]
def build_profile(code_findings: list[CodeFinding]) -> DataCollectionProfile: ...

# pages/checks.py
def collect_page_urls(meta) -> list[tuple[str, str]]:  # deduped (page_type, url)
def run_reachability(page_urls, fetched: dict[str, FetchedPage], *, has_privacy_url: bool) -> list[PageFinding]: ...

# pages/jury.py
class PageUnit(BaseModel):
    id: str; page_type: str; url: str; question: str; guideline_ref: str
    text: str; category: str | None = None
class PageJudge:      # from_model(name, model) / from_spec(spec) / async run(unit, grounding) / run_sync(unit, grounding)
class PageJury:       # __init__(judges, policy_name) / build(specs, policy)->PageJury|None / judge_one(unit, grounding)->PanelVerdict
def apply_page_jury(pages_by_type: dict[str, FetchedPage], profile: DataCollectionProfile, *,
                    jury: PageJury, grounding: str = "") -> list[PageFinding]: ...

# pages/analyzer.py
def analyze_pages(meta, *, fetcher, code_findings=None, jury=None, grounding=None) -> list[PageFinding]: ...
def build_pages_report(findings, pages_checked, *, fail_on="fail", jury_used=False) -> PagesReport: ...

# gate.py additions
def _page_level(f: PageFinding) -> Level: ...          # "block" if high else "warn"
# evaluate(...) gains: page_findings: list[PageFinding] | None = None
```

---

### Task 1: Data models + gate integration

**Files:**
- Modify: `src/asc_metadata_verifier/models.py` (add `PageFinding`, `PagesReport`; add `page_findings` to `GateReport`)
- Modify: `src/asc_metadata_verifier/gate.py` (add `_page_level`, fold `page_findings` into `evaluate`)
- Test: `tests/test_pages_models.py`, extend `tests/test_gate.py`

**Interfaces:**
- Consumes: existing `PanelVerdict`, `GateReport`, `evaluate`.
- Produces: `PageFinding`, `PagesReport`, `GateReport.page_findings`, `gate._page_level`, `evaluate(..., page_findings=...)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pages_models.py
from asc_metadata_verifier.models import GateReport, PageFinding, PagesReport

def test_page_finding_defaults():
    f = PageFinding(page_type="privacy", url="https://x/p", rule_id="page-unreachable",
                    category="privacy", severity="high", guideline_ref="5.1.1",
                    evidence="HTTP 404", detail="did not load")
    assert f.source == "static" and f.confidence == 1.0 and f.panel is None

def test_pages_report_defaults():
    r = PagesReport(status="PASS")
    assert r.findings == [] and r.pages_checked == 0 and r.jury_used is False

def test_gate_report_has_page_findings_default():
    assert GateReport(status="PASS", guidelines_available=True).page_findings == []
```

```python
# tests/test_gate.py (append)
from asc_metadata_verifier.models import PageFinding  # noqa: E402

def _pf(sev):
    return PageFinding(page_type="privacy", url="https://x", rule_id="r", category="privacy",
                       severity=sev, guideline_ref="5.1.1", evidence="e", detail="d")

def test_high_page_finding_blocks():
    r = evaluate([], [], page_findings=[_pf("high")])
    assert r.status == "BLOCK" and len(r.page_findings) == 1

def test_medium_page_finding_warns():
    assert evaluate([], [], page_findings=[_pf("medium")]).status == "WARN"

def test_page_findings_absent_is_unchanged():
    assert evaluate([], []).status == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pages_models.py tests/test_gate.py -q`
Expected: FAIL (`ImportError: cannot import name 'PageFinding'`).

- [ ] **Step 3: Implement models** — in `models.py`, add after `CodeReport` (so `PanelVerdict` is already defined):

```python
class PageFinding(BaseModel):
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
    status: Literal["PASS", "WARN", "BLOCK"]
    findings: list[PageFinding] = Field(default_factory=list)
    pages_checked: int = 0
    jury_used: bool = False
```

In `GateReport`, add: `page_findings: list[PageFinding] = Field(default_factory=list)`.

- [ ] **Step 4: Implement gate integration** — in `gate.py`, import `PageFinding`, then:

```python
def _page_level(finding: PageFinding) -> Level:
    """high -> block; medium/low -> warn. Mirrors `_code_level`."""
    return "block" if finding.severity == "high" else "warn"
```

Add `page_findings: list[PageFinding] | None = None` to `evaluate`'s signature; then:

```python
    page_findings = page_findings or []
    levels.extend(_page_level(f) for f in page_findings)
```

and pass `page_findings=page_findings` into the returned `GateReport`.

- [ ] **Step 5: Run tests to verify they pass** — `uv run pytest tests/test_pages_models.py tests/test_gate.py -q` → PASS; then `uv run pytest -q` (full suite unchanged) and `uv run ruff check src tests`.

- [ ] **Step 6: Commit**

```bash
git add src/asc_metadata_verifier/models.py src/asc_metadata_verifier/gate.py tests/test_pages_models.py tests/test_gate.py
git commit -m "feat(pages): PageFinding/PagesReport models + gate rollup"
```

---

### Task 2: HTML → text extraction

**Files:**
- Create: `src/asc_metadata_verifier/pages/__init__.py` (empty), `src/asc_metadata_verifier/pages/content.py`
- Test: `tests/test_pages_content.py`

**Interfaces:**
- Produces: `html_to_text(html: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pages_content.py
from asc_metadata_verifier.pages.content import html_to_text

def test_strips_tags_scripts_and_styles():
    html = "<html><head><style>.a{color:red}</style><script>evil()</script></head>" \
           "<body><h1>Privacy Policy</h1><p>We collect your email.</p></body></html>"
    text = html_to_text(html)
    assert "Privacy Policy" in text and "We collect your email." in text
    assert "evil()" not in text and "color:red" not in text

def test_empty_html_is_empty_text():
    assert html_to_text("").strip() == ""
```

- [ ] **Step 2: Run test to verify it fails** — `uv run pytest tests/test_pages_content.py -q` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement** (adapts the offline reducer proven in `guidelines/source.py`):

```python
# src/asc_metadata_verifier/pages/content.py
"""Reduce fetched HTML to clean, script/style-stripped text for the jury to
read. Pure, offline; adapts the reducer proven in guidelines/source.py."""

from __future__ import annotations

import re
from html import unescape


def html_to_text(html: str) -> str:
    without_scripts = re.sub(
        r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    without_style = re.sub(
        r"<style\b[^>]*>.*?</style>", " ", without_scripts, flags=re.DOTALL | re.IGNORECASE
    )
    with_breaks = re.sub(r"<[^>]+>", "\n", without_style)
    unescaped = unescape(with_breaks)
    lines = [line.strip() for line in unescaped.splitlines() if line.strip()]
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes** — `uv run pytest tests/test_pages_content.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/pages`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/pages/__init__.py src/asc_metadata_verifier/pages/content.py tests/test_pages_content.py
git commit -m "feat(pages): offline HTML->text extraction"
```

---

### Task 3: Fetcher protocol + FetchedPage + LocalPageFetcher

**Files:**
- Create: `src/asc_metadata_verifier/pages/fetch.py`
- Test: `tests/test_pages_fetch_local.py`

**Interfaces:**
- Consumes: `html_to_text` (Task 2).
- Produces: `FetchedPage`, `PageFetcher` (protocol), `LocalPageFetcher`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pages_fetch_local.py
from asc_metadata_verifier.pages.fetch import FetchedPage, LocalPageFetcher

def test_local_fetcher_returns_extracted_text():
    f = LocalPageFetcher({"https://x/p": "<h1>Privacy</h1><p>data</p>"})
    page = f.fetch("https://x/p")
    assert page.ok and "Privacy" in page.text and page.url == "https://x/p"

def test_local_fetcher_unknown_url_is_factual_not_fatal():
    page = LocalPageFetcher({}).fetch("https://x/missing")
    assert page.ok is False and page.text is None and page.error
```

- [ ] **Step 2: Run test to verify it fails** — `uv run pytest tests/test_pages_fetch_local.py -q` → FAIL.

- [ ] **Step 3: Implement** (the `FetchedPage` model, protocol, and `LocalPageFetcher`; `HttpPageFetcher` lands in Task 4):

```python
# src/asc_metadata_verifier/pages/fetch.py
"""Bounded, offline-safe page fetch. `LocalPageFetcher` (this task) backs
--pages-dir and tests; `HttpPageFetcher` (Task 4) adds the SSRF-guarded live
fetch. Neither ever raises into the analyzer; failures are factual states."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from asc_metadata_verifier.pages.content import html_to_text


class FetchedPage(BaseModel):
    url: str
    final_url: str | None = None
    status: int | None = None
    ok: bool = False
    text: str | None = None
    error: str | None = None


@runtime_checkable
class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...


class LocalPageFetcher:
    """Offline fetcher backed by a {url: html} map (from --pages-dir or tests)."""

    def __init__(self, pages: dict[str, str]):
        self._pages = dict(pages)

    def fetch(self, url: str) -> FetchedPage:
        if url not in self._pages:
            return FetchedPage(url=url, ok=False, error="not in local pages map")
        return FetchedPage(url=url, final_url=url, status=200, ok=True,
                           text=html_to_text(self._pages[url]))
```

- [ ] **Step 4: Run test to verify it passes** — `uv run pytest tests/test_pages_fetch_local.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/pages`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/pages/fetch.py tests/test_pages_fetch_local.py
git commit -m "feat(pages): FetchedPage + PageFetcher protocol + LocalPageFetcher"
```

---

### Task 4: HttpPageFetcher (SSRF guard + caps + manual redirects)

**Files:**
- Modify: `src/asc_metadata_verifier/pages/fetch.py` (add `HttpPageFetcher` + SSRF helpers)
- Test: `tests/test_pages_fetch_http.py`

**Interfaces:**
- Produces: `HttpPageFetcher`, module functions `_resolve(host)`, `_ip_blocked(ip)`, `_host_safe(host)`.

**SSRF design:** `_host_safe(host)` parses an IP literal directly (no DNS) or resolves via `_resolve` (monkeypatchable), and refuses any address that is private/loopback/link-local/reserved/multicast/unspecified. Redirects are followed manually, re-validating each hop. Body is streamed and capped at `max_bytes`.

- [ ] **Step 1: Write the failing tests** (no real network — `httpx.MockTransport` + monkeypatched `_resolve`)

```python
# tests/test_pages_fetch_http.py
import httpx
import pytest

from asc_metadata_verifier.pages import fetch as fetch_mod
from asc_metadata_verifier.pages.fetch import HttpPageFetcher


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_handler(request):
    return httpx.Response(200, html="<h1>Privacy</h1><p>We collect email.</p>")


def test_fetches_and_extracts_when_host_public(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["93.184.216.34"])  # public
    f = HttpPageFetcher(client=_client(_ok_handler))
    page = f.fetch("https://example.com/privacy")
    assert page.ok and "We collect email." in page.text and page.status == 200


def test_refuses_loopback_ip_literal_without_network():
    # host is an IP literal -> no DNS, guard refuses directly
    f = HttpPageFetcher(client=_client(_ok_handler))
    page = f.fetch("http://127.0.0.1/admin")
    assert page.ok is False and "block" in (page.error or "").lower()


def test_refuses_private_hostname(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["10.0.0.5"])
    f = HttpPageFetcher(client=_client(_ok_handler))
    page = f.fetch("https://internal.example.com/")
    assert page.ok is False and "block" in (page.error or "").lower()


def test_refuses_redirect_to_private(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve",
                        lambda host: ["93.184.216.34"] if host == "example.com" else ["127.0.0.1"])

    def redir_handler(request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, text="secret")

    f = HttpPageFetcher(client=_client(redir_handler))
    page = f.fetch("https://example.com/start")
    assert page.ok is False


def test_caps_response_size(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["93.184.216.34"])
    big = "<p>" + ("A" * 5000) + "</p>"

    def big_handler(request):
        return httpx.Response(200, html=big)

    f = HttpPageFetcher(client=_client(big_handler), max_bytes=1000)
    page = f.fetch("https://example.com/big")
    assert page.ok and len(page.text) <= 1000


def test_http_error_becomes_factual_error(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_resolve", lambda host: ["93.184.216.34"])

    def boom_handler(request):
        raise httpx.ConnectError("boom")

    f = HttpPageFetcher(client=_client(boom_handler))
    page = f.fetch("https://example.com/x")
    assert page.ok is False and page.error
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/test_pages_fetch_http.py -q` → FAIL (`ImportError: HttpPageFetcher`).

- [ ] **Step 3: Implement** — append to `pages/fetch.py`:

```python
import ipaddress
import socket
from urllib.parse import urlparse

import httpx


def _resolve(host: str) -> list[str]:
    """Resolve a hostname to IP strings. Module-level so tests can monkeypatch it."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> refuse
    return (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


def _host_safe(host: str) -> bool:
    try:
        ipaddress.ip_address(host)          # host is an IP literal -> check directly, no DNS
        return not _ip_blocked(host)
    except ValueError:
        pass
    try:
        ips = _resolve(host)
    except OSError:
        return False
    return bool(ips) and all(not _ip_blocked(ip) for ip in ips)


class HttpPageFetcher:
    """SSRF-guarded, bounded live fetch. http(s) only; refuses private hosts and
    private redirect targets; timeout + streamed size cap; manual redirects."""

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 10.0,
                 max_bytes: int = 2_000_000, max_redirects: int = 5):
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    def fetch(self, url: str) -> FetchedPage:
        current = url
        try:
            for _hop in range(self._max_redirects + 1):
                parsed = urlparse(current)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    return FetchedPage(url=url, final_url=current, ok=False,
                                       error=f"unsupported/invalid target: {current}")
                if not _host_safe(parsed.hostname):
                    return FetchedPage(url=url, final_url=current, ok=False,
                                       error="blocked host (private/loopback/unresolved)")
                request = self._client.build_request("GET", current)
                response = self._client.send(request, stream=True, follow_redirects=False)
                try:
                    if response.is_redirect and response.headers.get("location"):
                        current = str(httpx.URL(current).join(response.headers["location"]))
                        continue
                    if response.status_code >= 400:
                        return FetchedPage(url=url, final_url=current, status=response.status_code,
                                           ok=False, error=f"HTTP {response.status_code}")
                    body = b""
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) >= self._max_bytes:
                            break
                    text = html_to_text(body[:self._max_bytes].decode("utf-8", "replace"))
                    return FetchedPage(url=url, final_url=current, status=response.status_code,
                                       ok=True, text=text)
                finally:
                    response.close()
            return FetchedPage(url=url, final_url=current, ok=False, error="too many redirects")
        except httpx.HTTPError as exc:
            return FetchedPage(url=url, ok=False, error=str(exc)[:200])

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
```

- [ ] **Step 4: Run tests to verify they pass** — `uv run pytest tests/test_pages_fetch_http.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/pages`.
Note: the size-cap test caps at 1000 bytes of a 5000+ byte body; `text` is the extracted text of the truncated bytes, so `len(page.text) <= 1000` holds.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/pages/fetch.py tests/test_pages_fetch_http.py
git commit -m "feat(pages): SSRF-guarded HttpPageFetcher (caps + manual redirects)"
```

---

### Task 5: Data-collection profile

**Files:**
- Create: `src/asc_metadata_verifier/pages/profile.py`
- Test: `tests/test_pages_profile.py`

**Interfaces:**
- Consumes: `CodeFinding` (C).
- Produces: `DataCollectionProfile`, `build_profile(code_findings)`.

**Mapping:** from each `CodeFinding`, derive policy-relevant categories: `missing-usage-string`/`boilerplate-usage-string` → by `symbol` (the `NS*UsageDescription` key or API symbol) to a human category; `idfa-without-att` → `advertising identifier`. Required-reason / private-api / security rules contribute nothing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pages_profile.py
from asc_metadata_verifier.models import CodeFinding
from asc_metadata_verifier.pages.profile import build_profile

def _cf(rule_id, symbol):
    return CodeFinding(rule_id=rule_id, category="c", severity="high", guideline_ref="5.1.1",
                       file="A.swift", line=1, symbol=symbol, evidence="e", detail="d")

def test_usage_string_symbol_maps_to_category():
    p = build_profile([_cf("missing-usage-string", "AVCaptureDevice")])
    assert "camera" in p.categories

def test_idfa_maps_to_advertising_identifier():
    p = build_profile([_cf("idfa-without-att", "ASIdentifierManager")])
    assert "advertising identifier" in p.categories

def test_required_reason_contributes_nothing():
    p = build_profile([_cf("required-reason-api-undeclared", "UserDefaults")])
    assert p.categories == []

def test_categories_are_deduped_and_sorted():
    p = build_profile([_cf("missing-usage-string", "AVCaptureDevice"),
                       _cf("missing-usage-string", "AVCaptureDevice")])
    assert p.categories == ["camera"]
```

- [ ] **Step 2: Run test to verify it fails** — `uv run pytest tests/test_pages_profile.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# src/asc_metadata_verifier/pages/profile.py
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
```

- [ ] **Step 4: Run test to verify it passes** — `uv run pytest tests/test_pages_profile.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/pages`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/pages/profile.py tests/test_pages_profile.py
git commit -m "feat(pages): data-collection profile from code findings"
```

---

### Task 6: Deterministic reachability checks

**Files:**
- Create: `src/asc_metadata_verifier/pages/checks.py`
- Test: `tests/test_pages_checks.py`

**Interfaces:**
- Consumes: `FetchedPage` (Task 3), `AppMetadata`/`LocaleMetadata`, `PageFinding`.
- Produces: `collect_page_urls(meta)`, `run_reachability(page_urls, fetched, *, has_privacy_url)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pages_checks.py
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata
from asc_metadata_verifier.pages.checks import collect_page_urls, run_reachability
from asc_metadata_verifier.pages.fetch import FetchedPage

def _meta(**urls):
    return AppMetadata(locales=[LocaleMetadata(locale="en-US", **urls)])

def test_collect_page_urls_dedups_and_types():
    meta = AppMetadata(locales=[
        LocaleMetadata(locale="en-US", privacy_url="https://x/p", support_url="https://x/s"),
        LocaleMetadata(locale="de-DE", privacy_url="https://x/p")])  # dup privacy
    pairs = collect_page_urls(meta)
    assert ("privacy", "https://x/p") in pairs and ("support", "https://x/s") in pairs
    assert len([p for p in pairs if p == ("privacy", "https://x/p")]) == 1

def test_unreachable_privacy_is_high():
    pairs = [("privacy", "https://x/p")]
    fetched = {"https://x/p": FetchedPage(url="https://x/p", ok=False, error="HTTP 404")}
    out = run_reachability(pairs, fetched, has_privacy_url=True)
    hit = [f for f in out if f.rule_id == "page-unreachable"]
    assert len(hit) == 1 and hit[0].severity == "high"

def test_empty_page_is_medium():
    pairs = [("support", "https://x/s")]
    fetched = {"https://x/s": FetchedPage(url="https://x/s", ok=True, final_url="https://x/s", text="  ")}
    out = run_reachability(pairs, fetched, has_privacy_url=True)
    assert any(f.rule_id == "page-empty" and f.severity == "medium" for f in out)

def test_offsite_redirect_is_low():
    pairs = [("marketing", "https://x/m")]
    fetched = {"https://x/m": FetchedPage(url="https://x/m", ok=True,
                                          final_url="https://parked.example/m", text="hello world "*5)}
    out = run_reachability(pairs, fetched, has_privacy_url=True)
    assert any(f.rule_id == "page-offsite-redirect" and f.severity == "low" for f in out)

def test_missing_privacy_url_is_high():
    out = run_reachability([], {}, has_privacy_url=False)
    assert any(f.rule_id == "privacy-policy-missing" and f.severity == "high" for f in out)
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/test_pages_checks.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# src/asc_metadata_verifier/pages/checks.py
"""Deterministic reachability checks over fetched pages. Objective, offline-
capable (works on LocalPageFetcher output). No LLM."""

from __future__ import annotations

from urllib.parse import urlparse

from asc_metadata_verifier.models import AppMetadata, PageFinding
from asc_metadata_verifier.pages.fetch import FetchedPage

_FIELDS = (("privacy", "privacy_url"), ("support", "support_url"), ("marketing", "marketing_url"))
_UNREACHABLE_SEV = {"privacy": "high", "support": "high", "marketing": "medium"}
_GUIDELINE = {"privacy": "5.1.1", "support": "5.1.1", "marketing": "2.3.1"}
_EMPTY_MIN_CHARS = 40


def collect_page_urls(meta: AppMetadata) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for lm in meta.locales:
        for page_type, field in _FIELDS:
            url = getattr(lm, field)
            if url and (page_type, url) not in seen:
                seen.add((page_type, url))
                out.append((page_type, url))
    return out


def run_reachability(
    page_urls: list[tuple[str, str]],
    fetched: dict[str, FetchedPage],
    *,
    has_privacy_url: bool,
) -> list[PageFinding]:
    out: list[PageFinding] = []
    if not has_privacy_url:
        out.append(PageFinding(
            page_type="privacy", url="", rule_id="privacy-policy-missing", category="privacy",
            severity="high", guideline_ref="5.1.1", evidence="(no privacy_url declared)",
            detail="No privacy policy URL is declared; App Store requires one (5.1.1).",
            suggested_fix="Add a privacy policy URL in App Store Connect."))
    for page_type, url in page_urls:
        fp = fetched.get(url)
        if fp is None or not fp.ok:
            err = (fp.error if fp else "not fetched") or "unreachable"
            out.append(PageFinding(
                page_type=page_type, url=url, rule_id="page-unreachable", category=page_type,
                severity=_UNREACHABLE_SEV[page_type], guideline_ref=_GUIDELINE[page_type],
                evidence=err, detail=f"{page_type} URL did not load: {err}",
                suggested_fix="Ensure the URL is public and returns a real page."))
            continue
        if fp.text is not None and len(fp.text.strip()) < _EMPTY_MIN_CHARS:
            out.append(PageFinding(
                page_type=page_type, url=url, rule_id="page-empty", category=page_type,
                severity="medium", guideline_ref=_GUIDELINE[page_type], evidence="(near-empty page)",
                detail=f"{page_type} URL loaded but has almost no content.",
                suggested_fix="Publish real content at this URL."))
        if fp.final_url and urlparse(fp.final_url).hostname != urlparse(url).hostname:
            out.append(PageFinding(
                page_type=page_type, url=url, rule_id="page-offsite-redirect", category=page_type,
                severity="low", guideline_ref=_GUIDELINE[page_type],
                evidence=fp.final_url, detail=f"{page_type} URL redirects to a different host.",
                suggested_fix="Point the declared URL directly at the final page."))
    return out
```

- [ ] **Step 4: Run tests to verify they pass** — `uv run pytest tests/test_pages_checks.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/pages`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/pages/checks.py tests/test_pages_checks.py
git commit -m "feat(pages): deterministic reachability checks"
```

---

### Task 7: Page jury layer

**Files:**
- Create: `src/asc_metadata_verifier/pages/jury.py`
- Test: `tests/test_pages_jury.py`

**Interfaces:**
- Consumes: `JudgeSpec`/`load_judges` (config), `POLICIES`/`DEFAULT_POLICY`, `JudgeVote`/`PanelVerdict`/`RubricVerdict`, `FetchedPage`, `DataCollectionProfile`, `Agent`, `_model_ref`.
- Produces: `PageUnit`, `PageJudge`, `PageJury`, `apply_page_jury(...)`.

**Design:** direct analogue of `code/jury.py` (read it first). `PageJudge` wraps `Agent(output_type=RubricVerdict, system_prompt=PAGE_JURY_SYSTEM_PROMPT)`, error-isolated. `PageJury.judge_one` runs all judges concurrently under a semaphore and applies `POLICIES[policy_name]`. `apply_page_jury` builds units (privacy adequacy + one `privacy-code-mismatch` per profile category + support + marketing) over reachable pages and maps `fail`/`warn` consensus to `PageFinding(source="jury")`.

- [ ] **Step 1: Write the failing tests** (offline via `FunctionModel`, mirroring `tests/test_code_jury.py`)

```python
# tests/test_pages_jury.py
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.pages.fetch import FetchedPage
from asc_metadata_verifier.pages.jury import PageJudge, PageJury, PageUnit, apply_page_jury
from asc_metadata_verifier.pages.profile import DataCollectionProfile
from asc_metadata_verifier.models import RubricVerdict


def _rv(**kw):
    base = dict(dimension="d", verdict="fail", severity="high", confidence=0.9,
                rationale="r", locale="page", field="privacy")
    base.update(kw)
    return RubricVerdict(**base)


def _model(factory):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, factory().model_dump())])
    return FunctionModel(fn)


def _boom_model():
    def fn(messages, info):
        raise RuntimeError("kaboom")
    return FunctionModel(fn)


def _unit():
    return PageUnit(id="privacy-policy-inadequate", page_type="privacy", url="https://x/p",
                    question="q?", guideline_ref="5.1.1", text="some policy text")


def test_page_judge_error_isolation():
    vote = PageJudge.from_model("j", _boom_model()).run_sync(_unit(), "")
    assert vote.status == "error"


def test_cross_reference_flags_undisclosed_category():
    jury = PageJury([PageJudge.from_model("j", _model(lambda: _rv(verdict="fail", severity="high")))],
                    "majority_severe")
    pages = {"privacy": FetchedPage(url="https://x/p", ok=True, text="short policy")}
    profile = DataCollectionProfile(categories=["camera"])
    out = apply_page_jury(pages, profile, jury=jury, grounding="")
    assert any(f.rule_id == "privacy-code-mismatch" and f.category == "camera"
               and f.source == "jury" for f in out)


def test_disclosed_category_adds_nothing():
    jury = PageJury([PageJudge.from_model("j", _model(lambda: _rv(verdict="pass", severity="low")))],
                    "majority_severe")
    pages = {"privacy": FetchedPage(url="https://x/p", ok=True, text="we collect camera data")}
    profile = DataCollectionProfile(categories=["camera"])
    out = apply_page_jury(pages, profile, jury=jury, grounding="")
    assert all(f.rule_id != "privacy-code-mismatch" for f in out)
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/test_pages_jury.py -q` → FAIL.

- [ ] **Step 3: Implement** — model `pages/jury.py` on `code/jury.py`. Key pieces:

```python
# src/asc_metadata_verifier/pages/jury.py
"""Opt-in page jury. Off by default; reuses A's config + consensus + models with
page-specific units. Grounded ONLY in the fetched page text. Error-isolated; a
total judge failure yields the empty (pass) consensus, never a fabricated finding.
Direct analogue of code/jury.py."""

from __future__ import annotations

import asyncio
import time
from typing import Literal

from pydantic import BaseModel

from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES
from asc_metadata_verifier.models import JudgeVote, PageFinding, PanelVerdict, RubricVerdict
from asc_metadata_verifier.pages.fetch import FetchedPage
from asc_metadata_verifier.pages.profile import DataCollectionProfile

PAGE_JURY_SYSTEM_PROMPT = (
    "You are an App Store review judge inspecting the TEXT of one of the app's web "
    "pages (privacy policy, support, or marketing). Decide ONLY the specific question "
    "asked, grounded ONLY in the provided page text. If the text is insufficient to be "
    "sure, return verdict 'pass' with low confidence rather than guessing. Never invent "
    "a guideline_ref."
)


class PageUnit(BaseModel):
    id: str
    page_type: str
    url: str
    question: str
    guideline_ref: str
    text: str
    category: str | None = None


def _build_prompt(unit: PageUnit, grounding: str) -> str:
    parts = [f"Question: {unit.question}", f"Guideline: {unit.guideline_ref}",
             f"Page ({unit.page_type}): {unit.url}", "Page text:", unit.text[:6000]]
    if grounding:
        parts += ["Guideline text:", grounding]
    return "\n".join(parts)


class PageJudge:
    def __init__(self, name: str, agent):
        self.name = name
        self._agent = agent

    @classmethod
    def from_model(cls, name: str, model):
        from pydantic_ai import Agent
        return cls(name, Agent(model, output_type=RubricVerdict,
                               system_prompt=PAGE_JURY_SYSTEM_PROMPT))

    @classmethod
    def from_spec(cls, spec):
        from pydantic_ai import Agent
        from asc_metadata_verifier.judge.client import _model_ref
        return cls(spec.name, Agent(_model_ref(spec), output_type=RubricVerdict,
                                    system_prompt=PAGE_JURY_SYSTEM_PROMPT, defer_model_check=True))

    async def run(self, unit: PageUnit, grounding: str) -> JudgeVote:
        start = time.monotonic()
        try:
            result = await self._agent.run(_build_prompt(unit, grounding))
            update: dict[str, object] = {"locale": "page", "dimension": unit.id, "field": unit.page_type}
            if not grounding:
                update["guideline_ref"] = None
            verdict = result.output.model_copy(update=update)
        except Exception as exc:  # noqa: BLE001 - one judge's failure must not kill the jury
            return JudgeVote(judge=self.name, status="error", error=str(exc)[:300],
                             latency_ms=(time.monotonic() - start) * 1000)
        return JudgeVote(judge=self.name, status="voted", verdict=verdict,
                         latency_ms=(time.monotonic() - start) * 1000)

    def run_sync(self, unit: PageUnit, grounding: str) -> JudgeVote:
        return asyncio.run(self.run(unit, grounding))


class PageJury:
    def __init__(self, judges: list[PageJudge], policy_name: str, max_concurrency: int = 8):
        self.judges = list(judges)
        self.policy_name = policy_name if policy_name in POLICIES else DEFAULT_POLICY
        self.policy = POLICIES[self.policy_name]
        self.max_concurrency = max_concurrency

    @classmethod
    def build(cls, specs, policy_name: str, max_concurrency: int = 8) -> "PageJury | None":
        judges = [PageJudge.from_spec(s) for s in specs if s.available]
        return cls(judges, policy_name, max_concurrency) if judges else None

    def judge_one(self, unit: PageUnit, grounding: str) -> PanelVerdict:
        async def _run() -> PanelVerdict:
            sem = asyncio.Semaphore(self.max_concurrency)

            async def bounded(judge: PageJudge) -> JudgeVote:
                async with sem:
                    return await judge.run(unit, grounding)

            votes = list(await asyncio.gather(*[bounded(j) for j in self.judges]))
            cons, agr = self.policy(votes, locale="page", dimension=unit.id,
                                    default_field=unit.page_type)
            return PanelVerdict(locale="page", dimension=unit.id, field=unit.page_type, votes=votes,
                                consensus=cons, policy=self.policy_name, agreement=agr)

        return asyncio.run(_run())


def _finding(unit: PageUnit, pv: PanelVerdict, severity: str, category: str,
             evidence: str) -> PageFinding:
    return PageFinding(page_type=unit.page_type, url=unit.url, rule_id=unit.id, category=category,
                       severity=severity, guideline_ref=unit.guideline_ref, evidence=evidence,
                       detail=pv.consensus.rationale, source="jury", panel=pv,
                       confidence=pv.consensus.confidence)


def apply_page_jury(pages_by_type: dict[str, FetchedPage], profile: DataCollectionProfile, *,
                    jury: PageJury, grounding: str = "") -> list[PageFinding]:
    out: list[PageFinding] = []
    priv = pages_by_type.get("privacy")
    if priv and priv.ok and priv.text:
        u = PageUnit(id="privacy-policy-inadequate", page_type="privacy", url=priv.url,
                     question="Is this a genuine, adequate privacy policy (states what data is "
                     "collected, how it is used, and a contact)?", guideline_ref="5.1.1",
                     text=priv.text)
        pv = jury.judge_one(u, grounding)
        if pv.consensus.verdict in ("fail", "warn"):
            out.append(_finding(u, pv, "high", "privacy", priv.text[:120]))
        for cat in profile.categories:
            u = PageUnit(id="privacy-code-mismatch", page_type="privacy", url=priv.url,
                         question=f"The app's code accesses {cat}. Does this privacy policy "
                         f"disclose collecting or using {cat}?", guideline_ref="5.1.1",
                         text=priv.text, category=cat)
            pv = jury.judge_one(u, grounding)
            if pv.consensus.verdict in ("fail", "warn"):
                out.append(_finding(u, pv, "high", cat, f"code accesses {cat}; policy silent"))
    supp = pages_by_type.get("support")
    if supp and supp.ok and supp.text:
        u = PageUnit(id="support-inadequate", page_type="support", url=supp.url,
                     question="Does this support page offer a real way to get help or contact a "
                     "human (email, form, or clear instructions)?", guideline_ref="5.1.1",
                     text=supp.text)
        pv = jury.judge_one(u, grounding)
        if pv.consensus.verdict in ("fail", "warn"):
            out.append(_finding(u, pv, "medium", "support", supp.text[:120]))
    mkt = pages_by_type.get("marketing")
    if mkt and mkt.ok and mkt.text:
        u = PageUnit(id="marketing-overclaim", page_type="marketing", url=mkt.url,
                     question="Does this marketing copy overclaim, mention other platforms "
                     "(Android/Google Play), or mislead about the app?", guideline_ref="2.3.1",
                     text=mkt.text)
        pv = jury.judge_one(u, grounding)
        if pv.consensus.verdict in ("fail", "warn"):
            out.append(_finding(u, pv, "medium", "marketing", mkt.text[:120]))
    return out
```

- [ ] **Step 4: Run tests to verify they pass** — `uv run pytest tests/test_pages_jury.py -q` → PASS; full suite `uv run pytest -q` (offline, no keys); `uv run ruff check src/asc_metadata_verifier/pages`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/pages/jury.py tests/test_pages_jury.py
git commit -m "feat(pages): opt-in page jury (adequacy + privacy<->code cross-reference)"
```

---

### Task 8: Orchestrator

**Files:**
- Create: `src/asc_metadata_verifier/pages/analyzer.py`
- Test: `tests/test_pages_analyzer.py`

**Interfaces:**
- Consumes: `collect_page_urls`/`run_reachability`, `build_profile`, `apply_page_jury`, `evaluate`, `PagesReport`.
- Produces: `analyze_pages(meta, *, fetcher, code_findings=None, jury=None, grounding=None)`, `build_pages_report(...)`.

- [ ] **Step 1: Write the failing tests** (offline: `LocalPageFetcher` + optional injected `PageJury`)

```python
# tests/test_pages_analyzer.py
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata
from asc_metadata_verifier.pages.analyzer import analyze_pages, build_pages_report
from asc_metadata_verifier.pages.fetch import LocalPageFetcher

def _meta():
    return AppMetadata(locales=[LocaleMetadata(locale="en-US",
        privacy_url="https://x/p", support_url="https://x/s")])

def test_analyze_flags_unreachable_support_offline():
    fetcher = LocalPageFetcher({"https://x/p": "<p>We collect your email address here.</p>"})
    findings = analyze_pages(_meta(), fetcher=fetcher)   # support URL missing from map -> unreachable
    assert any(f.rule_id == "page-unreachable" and f.page_type == "support" for f in findings)

def test_build_pages_report_status_from_severity():
    fetcher = LocalPageFetcher({})   # both unreachable
    findings = analyze_pages(_meta(), fetcher=fetcher)
    rep = build_pages_report(findings, pages_checked=2)
    assert rep.status == "BLOCK" and rep.pages_checked == 2   # unreachable privacy/support are high

def test_deterministic_ordering():
    fetcher = LocalPageFetcher({})
    a = analyze_pages(_meta(), fetcher=fetcher)
    b = analyze_pages(_meta(), fetcher=fetcher)
    assert [(f.page_type, f.rule_id, f.url) for f in a] == [(f.page_type, f.rule_id, f.url) for f in b]
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/test_pages_analyzer.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# src/asc_metadata_verifier/pages/analyzer.py
"""Orchestrate the pages analysis: fetch each declared URL once, run
deterministic reachability, and (if a jury is provided) the interpretive +
cross-reference checks. Deterministic ordering. Pure aside from the injected
fetcher/jury."""

from __future__ import annotations

from asc_metadata_verifier.gate import evaluate
from asc_metadata_verifier.models import CodeFinding, PageFinding, PagesReport
from asc_metadata_verifier.pages.checks import collect_page_urls, run_reachability
from asc_metadata_verifier.pages.jury import apply_page_jury
from asc_metadata_verifier.pages.profile import build_profile


def analyze_pages(meta, *, fetcher, code_findings: list[CodeFinding] | None = None,
                  jury=None, grounding: str | None = None) -> list[PageFinding]:
    page_urls = collect_page_urls(meta)
    fetched = {}
    for _page_type, url in page_urls:
        if url not in fetched:
            fetched[url] = fetcher.fetch(url)
    has_privacy = any(lm.privacy_url for lm in meta.locales)
    findings = run_reachability(page_urls, fetched, has_privacy_url=has_privacy)
    if jury is not None:
        pages_by_type: dict[str, object] = {}
        for page_type, url in page_urls:
            pages_by_type.setdefault(page_type, fetched[url])
        profile = build_profile(code_findings or [])
        findings += apply_page_jury(pages_by_type, profile, jury=jury,
                                    grounding=grounding or "")
    findings.sort(key=lambda f: (f.page_type, f.rule_id, f.url))
    return findings


def build_pages_report(findings: list[PageFinding], pages_checked: int, *,
                       fail_on: str = "fail", jury_used: bool = False) -> PagesReport:
    status = evaluate([], [], fail_on=fail_on, page_findings=findings).status
    return PagesReport(status=status, findings=findings, pages_checked=pages_checked,
                       jury_used=jury_used)
```

- [ ] **Step 4: Run tests to verify they pass** — `uv run pytest tests/test_pages_analyzer.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/pages`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/pages/analyzer.py tests/test_pages_analyzer.py
git commit -m "feat(pages): analyzer orchestrator + PagesReport builder"
```

---

### Task 9: CLI `pages` command + rendering + `verify --pages`

**Files:**
- Modify: `src/asc_metadata_verifier/cli.py` (add `pages` command; add `--pages`/`--pages-dir`/`--code` handling to `verify`)
- Modify: `src/asc_metadata_verifier/report.py` (add `render_pages_report_text`/`_json`; extend `render_markdown`)
- Test: `tests/test_pages_cli.py`, extend `tests/test_report.py`

**Interfaces:**
- Consumes: `run_verify` (dry-run ingest), `_analyze_project` (Task 8 of sub-project C, in cli.py), `analyze_pages`/`build_pages_report`, `collect_page_urls`, `LocalPageFetcher`/`HttpPageFetcher`, `PageJury`, `evaluate`, `exit_code`.
- Produces: `asc-verify pages <src> [...]`, `verify --pages [--code] [--pages-dir]`, `_load_pages_dir`, `render_pages_report_text`/`_json`.

- [ ] **Step 1: Write the failing tests** (offline via `--pages-dir`)

```python
# tests/test_pages_cli.py
import json
from pathlib import Path
from typer.testing import CliRunner
from asc_metadata_verifier.cli import app

runner = CliRunner()

def _pages_dir(tmp_path: Path, pages: dict) -> Path:
    d = tmp_path / "pages"
    d.mkdir()
    manifest = {}
    for i, (url, html) in enumerate(pages.items()):
        fn = f"p{i}.html"
        (d / fn).write_text(html)
        manifest[url] = fn
    (d / "pages.json").write_text(json.dumps(manifest))
    return d

def test_pages_command_blocks_on_unreachable_privacy(tmp_path):
    # metadata.yaml declares privacy/support URLs; pages-dir supplies neither -> unreachable
    d = _pages_dir(tmp_path, {"https://only/support": "<p>contact us at help@x.com anytime</p>"})
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/metadata.yaml",
                              "--pages-dir", str(d)])
    assert res.exit_code == 1 and "page-unreachable" in res.output

def test_pages_command_json_format(tmp_path):
    d = _pages_dir(tmp_path, {})
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/metadata.yaml",
                              "--pages-dir", str(d), "--format", "json"])
    assert '"rule_id"' in res.output and '"pages_checked"' in res.output

def test_pages_missing_metadata_source_exits_2():
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/does_not_exist.yaml"])
    assert res.exit_code == 2

def test_verify_with_pages_folds_findings(tmp_path):
    d = _pages_dir(tmp_path, {})
    res = runner.invoke(app, ["verify", "--yaml", "tests/fixtures/metadata.yaml", "--dry-run",
                              "--pages", "--pages-dir", str(d)])
    assert "page-unreachable" in res.output
```

> Implementer: confirm `tests/fixtures/metadata.yaml` declares `privacy_url`/`support_url` (it does — see the fixture). The metadata's real URLs won't be in the pages-dir manifest, so they resolve `unreachable` offline — exactly what these tests assert.

```python
# tests/test_report.py (append)
from asc_metadata_verifier.models import PageFinding, PagesReport
from asc_metadata_verifier.report import render_pages_report_text, render_pages_report_json

def _pages_report():
    f = PageFinding(page_type="privacy", url="https://x/p", rule_id="page-unreachable",
                    category="privacy", severity="high", guideline_ref="5.1.1",
                    evidence="HTTP 404", detail="did not load")
    return PagesReport(status="BLOCK", findings=[f], pages_checked=1)

def test_render_pages_text_shows_url_and_guideline():
    out = render_pages_report_text(_pages_report())
    assert "https://x/p" in out and "5.1.1" in out and "BLOCK" in out

def test_render_pages_json_roundtrips():
    import json
    data = json.loads(render_pages_report_json(_pages_report()))
    assert data["status"] == "BLOCK" and data["findings"][0]["rule_id"] == "page-unreachable"
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/test_pages_cli.py tests/test_report.py -q` → FAIL.

- [ ] **Step 3: Implement rendering** (in `report.py`) — import `PageFinding`, `PagesReport`; add:

```python
def _render_page_findings(findings: list[PageFinding]) -> list[str]:
    if not findings:
        return []
    lines: list[str] = ["## Page findings", ""]
    by_type: dict[str, list[PageFinding]] = defaultdict(list)
    for f in findings:
        by_type[f.page_type].append(f)
    for page_type in sorted(by_type):
        lines.append(f"### {page_type}")
        for f in by_type[page_type]:
            tag = "jury" if f.source == "jury" else "static"
            lines.append(f"- [{f.severity}] {f.rule_id} ({f.guideline_ref}) [{tag}] {f.url}")
            lines.append(f"    {f.detail} — evidence: {f.evidence!r}")
            if f.suggested_fix:
                lines.append(f"    fix: {f.suggested_fix}")
        lines.append("")
    return lines


def render_pages_report_text(report: PagesReport) -> str:
    header = [f"Pages analysis: {report.status}",
              f"({report.pages_checked} pages, jury={report.jury_used})", ""]
    body = _render_page_findings(report.findings) or ["No page findings."]
    return "\n".join(header + body).rstrip() + "\n"


def render_pages_report_json(report: PagesReport) -> str:
    return report.model_dump_json(indent=2)
```

Extend `render_markdown` to append `_render_page_findings(report.page_findings)` (after the code-findings section).

- [ ] **Step 4: Implement the CLI** (in `cli.py`) — add imports (`render_pages_report_json`, `render_pages_report_text`), a `_load_pages_dir` helper, and the `pages` command; add `--pages`/`--pages-dir` to `verify`.

```python
def _load_pages_dir(pages_dir):
    """Build a LocalPageFetcher from a --pages-dir containing a pages.json
    manifest ({url: relative_html_file}). Exits 2 on a bad dir/manifest."""
    from pathlib import Path
    from asc_metadata_verifier.pages.fetch import LocalPageFetcher
    base = Path(pages_dir)
    manifest = base / "pages.json"
    if not manifest.is_file():
        typer.echo(f"Error: --pages-dir has no pages.json manifest: {pages_dir}", err=True)
        raise typer.Exit(code=2) from None
    try:
        mapping = json.loads(manifest.read_text())
        pages = {url: (base / rel).read_text() for url, rel in mapping.items()}
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: cannot read --pages-dir: {exc}", err=True)
        raise typer.Exit(code=2) from None
    return LocalPageFetcher(pages)


def _run_pages(*, meta, code_path, jury, judges_path, consensus, pages_dir, fail_on):
    """Shared for `pages` and `verify --pages`: returns list[PageFinding] + pages_checked + jury_used."""
    from asc_metadata_verifier.pages.analyzer import analyze_pages
    from asc_metadata_verifier.pages.checks import collect_page_urls
    from asc_metadata_verifier.pages.fetch import HttpPageFetcher

    fetcher = _load_pages_dir(pages_dir) if pages_dir else HttpPageFetcher()
    code_findings = None
    if code_path:
        code_findings = _analyze_project(code_path, "auto", None)[0]
    page_jury = None
    jury_used = False
    if jury:
        from asc_metadata_verifier.pages.jury import PageJury
        specs = _build_judge_set(judges_path, None, consensus).specs
        page_jury = PageJury.build(specs, consensus or DEFAULT_POLICY)
        jury_used = page_jury is not None
    findings = analyze_pages(meta, fetcher=fetcher, code_findings=code_findings, jury=page_jury)
    pages_checked = len({url for _t, url in collect_page_urls(meta)})
    return findings, pages_checked, jury_used


@app.command()
def pages(
    path: Path | None = typer.Argument(None, help="Fastlane root (or use --yaml / --asc-api-*)."),
    yaml_path: Path | None = typer.Option(None, "--yaml"),
    asc_api_app_id: str | None = typer.Option(None, "--asc-api-app-id"),
    asc_api_key_id: str | None = typer.Option(None, "--asc-api-key-id"),
    asc_api_issuer_id: str | None = typer.Option(None, "--asc-api-issuer-id"),
    asc_api_key: Path | None = typer.Option(None, "--asc-api-key"),
    code_path: str | None = typer.Option(None, "--code", help="Re-run C for the privacy<->code x-ref."),
    jury: bool = typer.Option(False, "--jury"),
    judges_path: Path | None = typer.Option(None, "--judges"),
    consensus: str = typer.Option(DEFAULT_POLICY, "--consensus"),
    pages_dir: str | None = typer.Option(None, "--pages-dir", help="Offline: dir with a pages.json manifest."),
    fail_on: FailOn = typer.Option(FailOn.fail, "--fail-on"),
    output_format: OutputFormat = typer.Option(OutputFormat.md, "--format"),
) -> None:
    """Fetch + analyze the app's privacy/support/marketing pages for rejection risk."""
    from asc_metadata_verifier.pages.analyzer import build_pages_report

    try:
        outcome = run_verify(path=path, yaml_path=yaml_path, asc_api_app_id=asc_api_app_id,
                             asc_api_key_id=asc_api_key_id, asc_api_issuer_id=asc_api_issuer_id,
                             asc_api_key=asc_api_key, dry_run=True)
    except IngestError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    try:
        findings, pages_checked, jury_used = _run_pages(
            meta=outcome.meta, code_path=code_path, jury=jury, judges_path=judges_path,
            consensus=consensus, pages_dir=pages_dir, fail_on=fail_on.value)
    except JudgeConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    report = build_pages_report(findings, pages_checked, fail_on=fail_on.value, jury_used=jury_used)
    if output_format is OutputFormat.json:
        typer.echo(render_pages_report_json(report))
    else:
        typer.echo(render_pages_report_text(report))
    raise typer.Exit(code=1 if report.status == "BLOCK" else 0)
```

For `verify --pages`: add options `pages: bool = typer.Option(False, "--pages")`, `pages_dir: str | None = typer.Option(None, "--pages-dir")` (reuse `code_path` from `verify --code`). After the `--code` fold block (or in place of it), when `pages` is set, call `_run_pages(meta=meta, code_path=code_path, jury=False, judges_path=None, consensus=DEFAULT_POLICY, pages_dir=pages_dir, fail_on=fail_on.value)` and rebuild the gate:

```python
    if pages:
        page_findings, _pc, _ju = _run_pages(
            meta=meta, code_path=str(code_path) if code_path else None, jury=False,
            judges_path=None, consensus=DEFAULT_POLICY, pages_dir=pages_dir, fail_on=fail_on.value)
        report = evaluate(report.verdicts, report.deterministic_findings, fail_on=fail_on.value,
                          guidelines_available=report.guidelines_available, panels=report.panels,
                          code_findings=report.code_findings, page_findings=page_findings)
```

(Place this after the existing `if code_path is not None:` fold so both code and page findings are present; when both `--code` and `--pages` are given, keep `report.code_findings` from the code fold and add page findings. Order the two folds so the final `report` carries both.)

> Implementer note: `verify` currently rebuilds the gate in the `--code` block. Make the two folds compose: compute `code_findings` once if `--code`, fold; then if `--pages`, fold page findings preserving `report.code_findings`. Verify with `test_verify_with_pages_folds_findings` (and keep `test_verify_with_code_folds_findings` from sub-project C green).

- [ ] **Step 5: Run tests to verify they pass** — `uv run pytest tests/test_pages_cli.py tests/test_report.py -q` → PASS; full suite `uv run pytest -q`; `uv run ruff check src tests`.

- [ ] **Step 6: Commit**

```bash
git add src/asc_metadata_verifier/cli.py src/asc_metadata_verifier/report.py tests/test_pages_cli.py tests/test_report.py
git commit -m "feat(pages): 'pages' CLI command + rendering + verify --pages"
```

---

### Task 10: Docs — README + BUILD_LOG

**Files:**
- Modify: `README.md` (add "Pages analysis (optional)" section)
- Modify: `BUILD_LOG.md` (add sub-project D entry: scope, honesty boundary, open items)

- [ ] **Step 1: README section** — document: `asc-verify pages <metadata>`; the fetch posture (bounded, SSRF-guarded, opt-in network) and its **DNS-rebind residual**; `--pages-dir` offline path; the deterministic reachability set; the `--code` + `--jury` cross-reference; what it does NOT do (no crawling, no full DNS-rebind hardening). Note **zero new core deps** (httpx already present).

- [ ] **Step 2: BUILD_LOG entry** — mirror the C entry: what shipped, honest open items (jury path needs network+keys; SSRF guard is resolve-then-check; cross-reference is jury-judged/soft; pages runs not persisted).

- [ ] **Step 3: Verify docs match reality** — run `asc-verify pages --help` and check the flags named in the README exist. Run the full suite `uv run pytest -q` and `uv run ruff check .` once more.

- [ ] **Step 4: Commit**

```bash
git add README.md BUILD_LOG.md
git commit -m "docs(pages): README + BUILD_LOG for sub-project D"
```

---

## Self-review notes (author)

- **Spec coverage:** Fetcher C1 → T3/T4; content C2 → T2; profile C3 → T5; reachability C4 → T6; jury C5 → T7; data model C6 → T1; orchestrator C7 → T8; CLI C8 → T9; testing strategy → each task's tests (offline via LocalPageFetcher / MockTransport / monkeypatched `_resolve` / FunctionModel); honesty/offline/SSRF invariants → Global Constraints per task; docs → T10. All covered.
- **Type consistency:** `PageFinding`/`PagesReport`/`FetchedPage`/`PageFetcher`/`LocalPageFetcher`/`HttpPageFetcher`/`DataCollectionProfile`/`build_profile`/`collect_page_urls`/`run_reachability`/`PageUnit`/`PageJudge`/`PageJury`/`apply_page_jury`/`analyze_pages`/`build_pages_report` names match across tasks. `evaluate(..., page_findings=)` matches T1 and T8/T9.
- **No new backend deps:** httpx is already core (`pyproject` `dependencies`); D adds none.
- **Dedup resolved:** `privacy-policy-missing` doesn't collide with `REQUIRED_FIELDS` (verified: privacy_url not in it).
- **Known real risks flagged in-plan:** the size-cap test semantics (T4); `verify` two-fold composition of `--code` + `--pages` (T9 note); confirm the metadata fixture declares the URLs (T9 note).
