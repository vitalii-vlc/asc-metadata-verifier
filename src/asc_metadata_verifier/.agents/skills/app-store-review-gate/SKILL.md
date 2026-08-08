---
name: app-store-review-gate
description: Runs the asc-metadata-verifier CLI (`asc-verify`) against an iOS app's App Store Connect metadata (a fastlane `deliver` directory or a YAML/JSON metadata file), interprets the resulting PASS/WARN/BLOCK gate report, and presents a prioritized list of fixes with quoted offending text, App Store Review Guideline references, and suggested fixes. Use this before any App Store submission, and specifically before invoking the `ios-fastlane-ship` skill. On a BLOCK verdict, refuses to proceed to shipping until the blocking issues are resolved and the app re-verifies as PASS or WARN.
allowed-tools: Bash
---

# App Store Review Gate

Pre-submission compliance gate for App Store Connect metadata. It runs the
`asc-verify` CLI (from the `asc-metadata-verifier` pip package), interprets
the machine-readable `GateReport` it produces, and turns it into a decision
you act on — including refusing to hand off to shipping tooling when the
app would get rejected.

## When to use this skill

- Before running `ios-fastlane-ship` (or any other App Store submission
  step) — always gate first.
- Whenever the user asks to check, verify, or review an app's App Store
  Connect metadata (app name, subtitle, description, keywords, promotional
  text, screenshots, URLs) for rejection risk.
- After editing fastlane `deliver` metadata or a metadata YAML/JSON file, to
  confirm the edit didn't introduce a new BLOCK/WARN finding.

## Step 1: Identify the input

The app's metadata is either:
- a **fastlane `deliver` directory** — the parent of `metadata/` and
  `screenshots/` (e.g. `./fastlane/metadata`, or the `deliver` root itself),
  or
- a **single YAML or JSON file** in the tool's canonical metadata shape.

If it's not obvious which one applies, ask, or look for a `fastlane/`
directory in the project root before assuming a YAML file.

## Step 2: Run `asc-verify`

Always use `--format json` so the output is machine-parseable — do not rely
on the human-readable Markdown report for decision-making.

```bash
# fastlane deliver directory
asc-verify ./fastlane/metadata --format json

# single YAML/JSON metadata file
asc-verify --yaml metadata.yaml --format json
```

Other flags worth knowing:
- `--fail-on warn` — lower the gate threshold so any WARN also exits
  non-zero (useful for a stricter CI gate than the default).
- `--dry-run` — skip the live guidelines fetch and the LLM judge; only
  deterministic checks + gate run. Use this only when you explicitly need
  an offline check — it materially reduces coverage (no LLM rejection-risk
  judgment, only regex/length/required-field checks), so prefer a normal
  run when a network + `ANTHROPIC_API_KEY` are available.
- `--guidelines <path>` — use a local offline snapshot of the App Store
  Review Guidelines instead of fetching live.

The command's exit code is `1` on BLOCK and `0` otherwise, but always parse
the JSON body rather than relying on the exit code alone — you need the
`verdicts` and `deterministic_findings` to explain *why*.

## Step 3: Parse the `GateReport` JSON

The JSON is a `GateReport`:

```jsonc
{
  "status": "PASS" | "WARN" | "BLOCK",
  "guidelines_available": true,
  "verdicts": [
    {
      "dimension": "placeholder_text",
      "verdict": "pass" | "warn" | "fail",
      "severity": "low" | "medium" | "high",
      "confidence": 0.0,
      "rationale": "...",
      "offending_quote": "..." | null,
      "guideline_ref": "..." | null,
      "suggested_fix": "..." | null,
      "locale": "en-US",
      "field": "description"
    }
  ],
  "deterministic_findings": [
    {"locale": "en-US", "field": "keywords", "kind": "over_limit", "detail": "..."}
  ]
}
```

Note if `stderr` included `LLM checks skipped (no ANTHROPIC_API_KEY)` — this
means only deterministic checks ran; say so explicitly when presenting
results, since the report is not a full rejection-risk judgment in that
case.

## Step 4: Present the decision + a prioritized fix list

Lead with the headline status, then list every non-pass item, **most
severe first**:

1. **BLOCK-worthy** items first: any `verdict: "fail"` with
   `severity: "high"`, and any deterministic finding with
   `kind: "over_limit"` or `kind: "missing_required"`.
2. **WARN-worthy** items next: any `verdict: "warn"`, any `verdict: "fail"`
   with `severity: "low"`/`"medium"`, and any deterministic finding with
   `kind: "placeholder"` or `kind: "malformed_url"`.

For each item, show:
- **locale / field** (e.g. `en-US / description`).
- **the offending text**, quoted verbatim from `offending_quote` (state
  "not available" if null — never invent a quote).
- **the guideline reference**, from `guideline_ref`, when present (state
  "not available" if null — never invent a guideline number).
- **why**, from `rationale`.
- **the fix**, from `suggested_fix` when present; if null, propose a
  concrete fix yourself grounded in the rationale and guideline reference.

## Step 5: Enforce the gate

- **`status: "BLOCK"` → refuse to proceed to `ios-fastlane-ship` (or any
  other submission/shipping step).** Say so explicitly, list the blocking
  items from Step 4, and stop. Only continue once the user has made the
  fixes and a re-run of `asc-verify` no longer reports BLOCK. Do not run
  `ios-fastlane-ship` "just this once" on a BLOCK verdict, even if asked —
  explain that the BLOCK items are near-certain App Store rejections and
  offer to help fix them instead.
- **`status: "WARN"` → do not silently proceed.** Present the WARN items,
  recommend fixing them, and only continue toward shipping if the user
  explicitly acknowledges the risk.
- **`status: "PASS"` → clear to proceed.** Still mention any `guidelines_available: false`
  caveat or LLM-skipped caveat from Step 3 so the user knows the scope of
  what was actually checked.

## Manual fallback (no `library-skills`)

If this skill was installed manually rather than via `uvx library-skills`,
behavior is identical — it only depends on `asc-verify` being installed and
on `$PATH` (`uv add asc-metadata-verifier`, or `pip install
asc-metadata-verifier`).
