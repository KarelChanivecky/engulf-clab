"""Pure license-pool manager and selector contracts.

This package deliberately has no Engulf dependency. Integrations own leases,
topology mutation, copying, and concrete selection policy.
"""

from .allocation import (
    LICENSE_ALLOCATION_HANDOFF_CONTEXT,
    LICENSE_POOL_REGISTRY_FILE,
    AllocationRequest,
    AllocationResult,
    LicenseAllocationHandoff,
    LicensePoolError,
    LicensePoolManager,
    LicensePoolRegistry,
    LicenseStrategy,
    PoolState,
    RegisteredPool,
    coerce_strategy,
)
from .api import (
    PoolManager,
    PoolManagerRequest,
    PoolManagerResult,
    PoolManagerStore,
    PoolSelector,
    run_pool_managers,
)

__all__ = [
    "LICENSE_ALLOCATION_HANDOFF_CONTEXT",
    "LICENSE_POOL_REGISTRY_FILE",
    "AllocationRequest",
    "AllocationResult",
    "LicenseAllocationHandoff",
    "LicensePoolError",
    "LicensePoolManager",
    "LicensePoolRegistry",
    "LicenseStrategy",
    "PoolState",
    "RegisteredPool",
    "coerce_strategy",
    "PoolManager",
    "PoolManagerRequest",
    "PoolManagerResult",
    "PoolManagerStore",
    "PoolSelector",
    "run_pool_managers",
]
