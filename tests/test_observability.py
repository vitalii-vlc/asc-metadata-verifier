from asc_metadata_verifier.observability import configure_logfire, span


def test_configure_logfire_runs_without_token_or_network(monkeypatch, capsys):
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)

    configure_logfire()

    # Console noise (if any) is captured here rather than leaking into
    # pytest's own output; we don't assert on its contents.
    capsys.readouterr()


def test_span_context_manager_works(capsys):
    configure_logfire()

    with span("x", foo="bar"):
        pass

    capsys.readouterr()
