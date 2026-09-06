from core.platform import metered_charge

def test_metering_calculates_charge_and_plan_limit():
    assert metered_charge(3, .02, 2) == {"units": 3, "charge": .06, "within_plan": False}
