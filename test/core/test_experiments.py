from core.evaluation import ExperimentSpec, compare_experiments


def test_experiment_spec_pins_all_versions():
    spec = ExperimentSpec("bench-v1", "model-v1", "prompt-v2", "rigel-v1", "route-v1")
    assert set(spec.as_dict()) == {"dataset", "model", "prompt_version", "agent_version", "routing_version"}


def test_experiment_comparison_reports_metrics_and_uncertainty():
    report = compare_experiments([{"quality": 0.8, "latency_ms": 100, "cost_usd": 0.1, "escalated": 0}] * 20, minimum_samples=20)
    assert report["insufficient_samples"] is False
    assert report["metrics"]["quality"]["mean"] == 0.8
    assert report["metrics"]["quality"]["standard_error"] == 0
