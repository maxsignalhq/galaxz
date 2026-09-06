import pytest
from core.platform import MigrationPlan

def test_migration_plan_is_tenant_aware_and_validated():
    MigrationPlan("v2", ("t1", "t2")).validate()
    with pytest.raises(ValueError):
        MigrationPlan("v2", ("t1", "t1")).validate()
