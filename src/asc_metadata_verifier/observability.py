"""Logfire observability wiring.

`configure_logfire()` sets up Logfire once at process start. With no
`LOGFIRE_TOKEN` in the environment, `send_to_logfire="if-token-present"`
keeps everything local-only and performs no network I/O — this is what
makes the tool safe to run offline / in CI without credentials.

`console=False` disables Logfire's default local console span printing.
Without it, Logfire echoes every span's start/end straight to stdout, which
would corrupt the CLI's own stdout output -- most concretely `asc-verify
--format json`, which must emit ONLY raw, parseable JSON on stdout.

`span(name, **attrs)` is a thin wrapper around `logfire.span` so callers
elsewhere in the codebase (the CLI, the judge) don't need to import
`logfire` directly.
"""

from __future__ import annotations

from typing import Any

import logfire

# Reconfiguring Logfire swaps out the tracer provider, and any span already in
# flight is silently discarded along with everything nested under it. Every
# command entry point calls `configure_logfire()`, and commands compose (the
# `verify` root span wraps `run_verify`, which calls it again), so the second
# and later calls must be no-ops.
_configured = False


def configure_logfire() -> None:
    """Configure Logfire for this process. Idempotent.

    Safe to call with no `LOGFIRE_TOKEN` set: `send_to_logfire="if-token-present"`
    means Logfire configures itself for local-only operation and does not
    attempt any network I/O when no token is present. `console=False` keeps
    span output out of stdout/stderr entirely (see module docstring).
    """
    global _configured
    if _configured:
        return

    logfire.configure(
        send_to_logfire="if-token-present",
        service_name="asc-metadata-verifier",
        console=False,
    )
    logfire.instrument_pydantic_ai()
    _configured = True


def span(name: str, **attrs: Any) -> Any:
    """Return a Logfire span context manager.

    Usage: `with span("ingest", source="fastlane"): ...`
    """
    return logfire.span(name, **attrs)
