from core.operations import run_drill_suite


def test_drill_suite_records_failures_and_continues():
    results = run_drill_suite({"queue-outage": lambda: (_ for _ in ()).throw(RuntimeError("redis unavailable")), "restore": lambda: None})
    assert [result.name for result in results] == ["queue-outage", "restore"]
    assert results[0].outcome == "failed"
    assert results[0].error == "redis unavailable"
    assert results[1].outcome == "passed"
