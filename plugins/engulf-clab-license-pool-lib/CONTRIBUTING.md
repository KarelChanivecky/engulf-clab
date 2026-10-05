# Contributing

`engulf_clab_license_pool_lib` owns the pure pool-manager contracts and
persisted registration/state mechanics. The product plugin owns the concrete
selector, leases, topology mutation, copying, callbacks, and diagnostics. Do
not add framework imports or hidden I/O to this package.

Keep `LicensePoolAvailability` as a path-free, tri-state signal. The owning
license-pool plugin reads its own registry and publishes that value during
`before_goal`; consumers must use the invocation context instead of assuming
that plugin-scoped state is shared.

Validate with:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-license-pool-lib/src
.venv/bin/python -m pytest -q plugins/engulf-clab-license-pool-lib/tests
```
