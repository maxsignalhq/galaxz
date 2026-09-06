from core.onboarding import run_onboarding_checks

def test_onboarding_reports_failed_clean_team_steps():
    result = run_onboarding_checks({"setup": True, "first_goal": False})
    assert result["status"] == "blocked"
    assert result["failures"] == ["first_goal"]
