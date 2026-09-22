# Library API

The library provides framework-neutral pool-manager and selector contracts,
plus the reusable persisted registration manager. It does not import Engulf,
perform logging, or discover license files.

```python
from pathlib import Path

from engulf_clab_license_pool_lib import (
    LicensePoolManager,
    PoolManagerRequest,
    run_pool_managers,
)

manager = LicensePoolManager(user_state_store)
result = run_pool_managers(
    (manager,),
    manager,
    PoolManagerRequest(path=Path("/srv/licenses/enterprise"), kind="linux"),
)
assert result.changed is True
```

`PoolManager` implementations may add or remove registered pools. A manager
may return `PoolManagerResult(preempt=True)` to stop later managers from
running for the same init-pool request. The caller owns manager ordering and
must stop the chain only after recording the manager's mutations.

Registered pools are a shared library contract rather than private plugin
state:

```python
from engulf_clab_license_pool_lib import LicensePoolManager

manager = LicensePoolManager(api.state(StateScope.USER))
for pool in manager.registered_pools():
    ...
```

An alternate allocation plugin can publish
`LicenseAllocationHandoff(provider_id=...)` in
`LICENSE_ALLOCATION_HANDOFF_CONTEXT`. The standard adapter then skips its
deployment allocation path; the alternate provider owns leases, copies,
rollback, and destroy cleanup.
