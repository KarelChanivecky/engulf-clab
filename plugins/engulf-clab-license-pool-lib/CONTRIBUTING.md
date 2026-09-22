# Contributing

`engulf_clab_license_pool_lib` owns the pure pool-manager contracts and
persisted registration/state mechanics. The product plugin owns the concrete
selector, leases, topology mutation, copying, callbacks, and diagnostics. Do
not add framework imports or hidden I/O to this package.

Validate with:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-license-pool-lib/src
.venv/bin/python -m pytest -q plugins/engulf-clab-license-pool-lib/tests
```
