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


def test_configure_logfire_twice_does_not_drop_an_already_open_span(monkeypatch):
    # Reconfiguring Logfire swaps the tracer provider, which silently discards
    # spans that are already in flight. `configure_logfire` is called at every
    # command entry, so a second call must be a no-op or any enclosing span --
    # and everything under it -- vanishes from the trace.
    import logfire
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from asc_metadata_verifier import observability

    monkeypatch.setattr(observability, "_configured", False, raising=False)
    exporter = InMemorySpanExporter()
    logfire.configure(
        send_to_logfire=False, service_name="obs-test", console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    monkeypatch.setattr(observability, "_configured", True, raising=False)

    with span("outer"):
        configure_logfire()
        with span("inner"):
            pass

    assert {s.name for s in exporter.get_finished_spans()} == {"outer", "inner"}
