from core.observability import MetricsRegistry


def test_metrics_aggregate_and_drop_unbounded_identifiers():
    metrics = MetricsRegistry()
    metrics.observe("jobs.completed", agent="rigel", goal_id="goal-1")
    metrics.observe("jobs.completed", agent="rigel", goal_id="goal-2")
    samples = metrics.snapshot()
    assert len(samples) == 1
    assert samples[0].value == 2
    assert samples[0].labels == (("agent", "rigel"),)


def test_llm_usage_can_attribute_model_and_cost_without_goal_labels():
    metrics = MetricsRegistry()
    metrics.observe("llm.tokens", 120, model="test-model", skill="code_generation")
    metrics.observe("llm.cost_usd", 0.03, model="test-model", skill="code_generation")
    assert {sample.name for sample in metrics.snapshot()} == {"llm.tokens", "llm.cost_usd"}
