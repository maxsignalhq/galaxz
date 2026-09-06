"""Hosted-platform safety primitives for tenant operations."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class MigrationPlan:
    version: str
    tenant_ids: tuple[str, ...]
    reversible: bool = True

    def validate(self) -> None:
        if not self.version or not self.tenant_ids or len(set(self.tenant_ids)) != len(self.tenant_ids):
            raise ValueError("migration plan must have unique tenants and a version")

def distribute_tenants(tenant_ids: list[str], worker_count: int) -> list[list[str]]:
    if worker_count < 1:
        raise ValueError("worker_count must be positive")
    buckets = [[] for _ in range(min(worker_count, max(1, len(tenant_ids))))]
    for index, tenant_id in enumerate(tenant_ids):
        buckets[index % len(buckets)].append(tenant_id)
    return buckets
