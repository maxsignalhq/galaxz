from core.evaluation import score_outcome


def test_outcome_score_combines_objective_gates_and_human_decision():
    result = score_outcome(tests=True, build=True, lint=False, security=True, acceptance=True, human_decision="accepted")
    assert result["quality_score"] == 0.8
    assert result["human_decision"] == "accepted"


def test_infrastructure_failure_is_not_model_quality_failure():
    result = score_outcome(tests=False, build=False, lint=False, security=False, acceptance=False, infrastructure_failure=True, human_decision="rejected")
    assert result["quality_score"] is None
    assert result["infrastructure_failure"] is True
