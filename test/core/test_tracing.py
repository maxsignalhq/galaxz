from core.observability import Tracer


def test_tracing_connects_child_spans_and_redacts_prompt_attributes():
    spans = []
    tracer = Tracer(spans.append)
    with tracer.span("api.request", goal_id="goal-1") as parent:
        with tracer.span("llm.call", prompt="private prompt") as child:
            assert child.parent_id == parent.span_id
            assert child.trace_id == parent.trace_id
            assert child.attributes["prompt"] == "[REDACTED]"
    assert [span.name for span in spans] == ["llm.call", "api.request"]


def test_trace_export_failure_does_not_break_work():
    def fail(_span):
        raise RuntimeError("telemetry unavailable")

    with Tracer(fail).span("worker.attempt"):
        pass
