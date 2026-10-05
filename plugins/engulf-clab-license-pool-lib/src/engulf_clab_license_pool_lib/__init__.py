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
    LICENSE_POOL_AVAILABILITY_CONTEXT,
    LicensePoolAvailability,
    PoolManager,
    PoolManagerRequest,
    PoolManagerResult,
    PoolManagerStore,
    PoolSelector,
    license_pool_availability,
    publish_license_pool_availability,
    run_pool_managers,
)

__all__ = [
    "LICENSE_ALLOCATION_HANDOFF_CONTEXT",
    "LICENSE_POOL_AVAILABILITY_CONTEXT",
    "LICENSE_POOL_REGISTRY_FILE",
    "AllocationRequest",
    "AllocationResult",
    "LicenseAllocationHandoff",
    "LicensePoolAvailability",
    "LicensePoolError",
    "LicensePoolManager",
    "LicensePoolRegistry",
    "LicenseStrategy",
    "PoolManager",
    "PoolManagerRequest",
    "PoolManagerResult",
    "PoolManagerStore",
    "PoolSelector",
    "PoolState",
    "RegisteredPool",
    "coerce_strategy",
    "license_pool_availability",
    "publish_license_pool_availability",
    "run_pool_managers",
]
