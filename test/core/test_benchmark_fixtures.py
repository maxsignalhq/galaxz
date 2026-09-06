from core.evaluation import load_fixtures


def test_benchmark_fixtures_are_pinned_and_cover_required_workflows():
    fixtures = load_fixtures()
    assert {fixture.workflow for fixture in fixtures} == {"code-generation", "bug-fix", "refactor", "tests", "multi-step"}
    assert {fixture.language for fixture in fixtures} == {"python", "typescript"}
    assert all(len(fixture.base_commit) == 40 for fixture in fixtures)
