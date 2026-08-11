# Pages Analyzer — Design Spec (v2, sub-project D)

> Pre-registration commit — scope + design fixed **before** any feature code
> (honest-velocity method, mirroring v1, the jury, persistence, and the code
> analyzer). Date: 2026-08-11.
>
> Fourth of five v2 sub-projects. The last — the HTML report generator (E) —
> gets its own spec → plan → build cycle and is **out of scope here**. D analyzes
> the app's **external web pages** (privacy policy / support / marketing URLs)
> against the App Store Review Guidelines **and** against what the code (C)
> actually collects.

**Goal:** add an **additive**, **opt-in** `pages` capability that fetches the
app's declared privacy/support/marketing URLs, runs **deterministic reachability**
checks, and (opt-in jury) judges **guideline compliance** per page plus the
crown-jewel **privacy-policy ↔ code cross-reference** — does the policy disclose
what C found the app actually collects — folding findings into the same
PASS/WARN/BLOCK gate.

**Architecture (one line):** a new `pages/` package — a bounded, SSRF-guarded
`PageFetcher` (httpx, offline `LocalPageFetcher` for tests) → deterministic
reachability `checks.py` → an opt-in `PageJury` (reuses A's `JudgeSpec` +
consensus + `PanelVerdict`) that judges page adequacy and cross-references a
`DataCollectionProfile` built from C's `CodeFinding`s. A standalone
`asc-verify pages <metadata> [--code <project>]` command yields a `PagesReport`;
`asc-verify verify <meta> --pages` folds `PageFinding`s into the unified
`GateReport`.

**Tech stack:** Python 3.11+ (uv) · pydantic v2 · typer · **httpx (already a core
dependency — no new core dep)** · stdlib `ipaddress`/`socket` (SSRF guard) ·
reuses `guidelines/source.py`'s offline HTML→text reducer, C's analyzer +
`CodeFinding`, and A's `judge/` panel. The jury layer is opt-in (API keys by
env-var reference).

---

## Global constraints

- **Additive / backward compatible (hard):** with no `pages` command and no
  `--pages` flag, behavior is **byte-identical to today** — `verify`/`code`/
  `history`/`diff`/`similar` and bare `asc-verify <path>` all pass unchanged, do
  no extra I/O, and pull **zero new core dependencies** (httpx is already a core
  dep for the guidelines fetch and the ASC API adapter).
- **Opt-in network (honest):** `pages` **does** hit the network by design — it
  fetches live pages, like the guidelines fetch. This is clearly documented, not
  hidden. `--pages-dir` (a URL→saved-HTML manifest) gives a **fully offline**
  path; the whole test suite runs offline via an injected `LocalPageFetcher`.
- **Never fabricate (honesty invariant):** a fetch failure produces a factual
  `unreachable`/`empty` state, never invented page content. A
  `privacy-code-mismatch` is raised **only** by the jury from the real fetched
  text and is tagged `source="jury"` with the full vote record; disclosure is
  never asserted deterministically. Missing profile (no `--code`) or jury-off →
  those checks simply don't run, they are never guessed.
- **SSRF guard (hard):** http(s) only; the resolved host IP is refused if
  private (RFC1918), loopback, link-local, or reserved; redirects are followed
  manually with **each hop re-validated** (hop cap ~5); connect/read timeout
  (~10s) and a response-size cap (~2 MB). **Honest residual, documented:** this
  is resolve-then-check, so DNS-rebinding is a known bypass not hardened in this
  build.
- **Curated / bounded:** the data-category mapping and the jury question set are
  curated and documented; the cross-reference covers only policy-relevant
  categories (camera/location/contacts/photos/mic/calendar/health + advertising
  identifier), **not** the required-reason manifest categories.
- **Secrets by reference:** jury mode reuses the env-var-ref `JudgeSpec` config;
  no key material in output or errors.

---

## Component 1 — Fetcher (`pages/fetch.py`)

`PageFetcher` protocol:

```
class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...

class FetchedPage(BaseModel):
    url: str
    final_url: str | None = None
    status: int | None = None
    ok: bool = False
    text: str | None = None       # extracted clean text when ok; None on failure
    error: str | None = None      # factual reason on failure
```

- **`HttpPageFetcher`** — one bounded `httpx.Client` (injectable for tests).
  Rejects non-http(s) schemes. Before connecting, resolves the host
  (`socket.getaddrinfo`) and refuses any address that is private/loopback/
  link-local/reserved (`ipaddress`). Auto-redirects disabled; each `Location`
  is re-validated the same way, hop-capped. Timeout + size cap applied. Extracts
  clean text via Component 2 when `ok`. On **any** exception/failure → `ok=False`,
  factual `error`, `text=None` — never raises into the analyzer.
- **`LocalPageFetcher`** — built from a `dict[url, html]`; returns a `FetchedPage`
  with `ok=True`, `text=<extracted>` (or `ok=False` if the URL isn't in the map).
  Fully offline; backs `--pages-dir` and every test.

## Component 2 — Content extraction (`pages/content.py`)

`html_to_text(html: str) -> str` — reduce HTML to clean, script/style-stripped
text for the jury to read, adapting the offline reducer already proven in
`guidelines/source.py` (`_html_to_lines`). Pure, offline, no network.

## Component 3 — Data-collection profile (`pages/profile.py`)

```
class DataCollectionProfile(BaseModel):
    categories: list[str]         # human data categories the policy should disclose

def build_profile(code_findings: list[CodeFinding]) -> DataCollectionProfile: ...
```

Maps only **policy-relevant** categories from C's findings (a curated
`rule_id/symbol → category` table):

- usage-string rules (`missing-usage-string`, `boilerplate-usage-string`) →
  `camera` · `location` · `contacts` · `photos` · `microphone` · `calendar` ·
  `health` (by the offending symbol/key).
- `idfa-without-att` → `advertising identifier / tracking`.

Required-reason manifest categories (UserDefaults, boot time, disk space) are
**excluded** — they belong to `PrivacyInfo.xcprivacy`, not the privacy-policy
narrative. Documented as a deliberate, honest boundary.

## Component 4 — Deterministic reachability (`pages/checks.py`)

Objective checks over a `FetchedPage` (live or local); no LLM, offline-capable.

| rule_id | detects | guideline | severity |
|---|---|---|---|
| `page-unreachable` | declared URL failed to load (network error, timeout, 4xx/5xx) | 5.1.1 (privacy/support), 2.3.x (marketing) | high for privacy/support; medium for marketing |
| `page-empty` | 2xx but near-empty extracted text (below a small char threshold) | 5.1.1 / 2.3.x | medium |
| `page-offsite-redirect` | `final_url` host ≠ declared host | informational | low |
| `privacy-policy-missing` | no `privacy_url` declared in any locale | 5.1.1 | high |

`privacy-policy-missing` **must be de-duplicated against the metadata layer**:
the plan checks whether `privacy_url` is already in
`limits.REQUIRED_FIELDS`/covered by `run_deterministic`'s `missing_required`; if
so, D does not double-flag it (D owns it only if the metadata layer doesn't).

## Component 5 — Jury interpretive layer (`pages/jury.py`)

Opt-in (`--jury` + judges config); **off by default; offline default intact**.
Mirrors `code/jury.py` (`PageJudge`/`PageJury`) reusing A's consensus `POLICIES`,
`JudgeVote`/`PanelVerdict`, and error isolation. Grounded **only** in the actual
fetched page text.

| rule_id | unit | guideline | severity |
|---|---|---|---|
| `privacy-policy-inadequate` | is the fetched text a genuine privacy policy (states what's collected, how used, contact)? | 5.1.1 | high |
| `privacy-code-mismatch` | **crown jewel** — one unit per profile category: "the code accesses {category}; does this policy disclose it?" `fail`/`warn` → undisclosed-collection finding; `pass` → nothing | 5.1.1 | high |
| `support-inadequate` | does the support page offer a real way to get help / contact a human? | 5.1.1 | medium |
| `marketing-overclaim` | does the marketing copy overclaim, mention other platforms, or mislead vs the app's actual metadata? | 2.3 / 2.3.1 | medium |

`privacy-code-mismatch` runs only when `--code` produced a non-empty profile
**and** `--jury` is on. Every jury item is a `PageFinding` with `source="jury"`
carrying the full `PanelVerdict`. A total judge failure yields the consensus
policy's empty (pass) verdict — a broken jury never fabricates a finding.

## Component 6 — Data model (`models.py`, beside `CodeFinding`)

```
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
    confidence: float = 1.0
    source: Literal["static", "jury"] = "static"
    panel: PanelVerdict | None = None

class PagesReport(BaseModel):
    status: Literal["PASS", "WARN", "BLOCK"]
    findings: list[PageFinding]
    pages_checked: int
    jury_used: bool
```

`GateReport` gains `page_findings: list[PageFinding] = []`; `evaluate(...)` gains
a `_page_level` classifier (high→block, medium/low→warn, mirroring
`_code_level`/`_DETERMINISTIC_LEVEL`) and folds `page_findings` into the rollup.

## Component 7 — Orchestrator (`pages/analyzer.py`)

```
def analyze_pages(
    meta: AppMetadata,
    *,
    fetcher: PageFetcher,
    code_findings: list[CodeFinding] | None = None,
    jury: PageJury | None = None,
) -> list[PageFinding]: ...
```

De-duplicates the declared privacy/support/marketing URLs across locales (each
distinct URL fetched once, tagged with its page type), fetches via the injected
`fetcher`, runs the deterministic checks, and — when `jury` is provided — the
interpretive checks plus the `privacy-code-mismatch` cross-reference over
`build_profile(code_findings)`. Deterministic ordering (sort by
`(page_type, rule_id, url)`).

## Component 8 — CLI (`cli.py`)

```
asc-verify pages <metadata-source>
    [--code <project-path>]          # re-run C to build the profile (cross-reference)
    [--jury] [--judges <judges.yaml>] [--consensus <policy>]
    [--pages-dir <dir>]              # offline: a pages.json manifest {url: file}
    [--fail-on fail|warn] [--format md|json]
```

- Ingests metadata via the SAME adapters as `verify` (fastlane path / `--yaml` /
  ASC API) to obtain the declared URLs; builds an `HttpPageFetcher` (or a
  `LocalPageFetcher` from `--pages-dir`); if `--code` is given, runs C's analyzer
  to get `code_findings`; runs `analyze_pages`; renders a `PagesReport`.
- Exit code mirrors the existing contract: **1 for BLOCK, 0 otherwise**; **2**
  for input/usage errors (bad metadata source, unreadable `--pages-dir`,
  malformed judges config). `--fail-on warn` promotes warn-level to BLOCK inside
  `evaluate`.
- `asc-verify verify <meta> --pages [--code <project>]` folds `PageFinding`s into
  the unified `GateReport` (rebuilds the gate via `evaluate(..., page_findings=)`,
  same pattern as `verify --code`). Without `--pages`, `verify` is unchanged.

Rendering: `report.py` gains `render_pages_report_text`/`_json` and a
`_render_page_findings` section appended to `render_markdown` when
`page_findings` is non-empty (mirrors the code-findings rendering).

---

## Testing strategy

- **`HttpPageFetcher`** against **mocked httpx** (like `tests/test_ingest_asc_api.py`),
  plus explicit **SSRF tests**: a URL resolving to `127.0.0.1`/`10.0.0.0/8` is
  refused with a factual error; a redirect whose target resolves private is
  refused; an oversize body is capped; a timeout becomes a factual `error`.
  **No real network.**
- **`LocalPageFetcher`** + `--pages-dir` with saved-HTML fixtures.
- **Deterministic checks** via constructed `FetchedPage`s (unreachable / empty /
  offsite / missing privacy URL).
- **`build_profile`** from `CodeFinding` lists (usage-string → categories; IDFA →
  tracking; required-reason excluded).
- **`PageJury`** fully offline via `FunctionModel` (like `tests/test_code_jury.py`):
  `privacy-policy-inadequate` fail; `privacy-code-mismatch` `fail`=undisclosed →
  finding, `pass`=disclosed → none; error isolation → `error` vote.
- **Gate integration** (`_page_level` rollup) + **`pages` CLI** + **`verify --pages`**
  with an injected `LocalPageFetcher` (offline).
- **Backward-compat:** the full existing suite passes unchanged; `verify` without
  `--pages` does zero extra I/O.
- **Determinism:** analyzing the same fixtures twice yields byte-identical
  ordered findings.

---

## Out of scope (kept honest & tight)

- Link-crawling / following links to *find* a privacy policy or contact page.
- Persisting `pages` runs via the repository (B). `PagesReport` is a serializable
  pydantic model, so it slots into the existing `Repository` later — not wired
  this build.
- Full DNS-rebinding hardening (pinning the validated IP into the connection).
  The resolve-then-check guard and its residual are documented, not overclaimed.
- The E HTML report generator — its own spec.
