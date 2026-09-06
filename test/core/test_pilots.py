import pytest
from core.pilots import Pilot

def test_pilot_lifecycle_is_immutable():
    pilot = Pilot("org", "repo", "partner", "bugfix").advance("active")
    assert pilot.status == "active"
    with pytest.raises(ValueError):
        pilot.advance("unknown")
