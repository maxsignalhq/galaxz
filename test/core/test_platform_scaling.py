from core.platform import distribute_tenants

def test_tenants_are_evenly_distributed_across_workers():
    assert distribute_tenants(["a", "b", "c", "d"], 2) == [["a", "c"], ["b", "d"]]
