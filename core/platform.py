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
