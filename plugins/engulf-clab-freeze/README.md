# engulf-clab-freeze

Creates a shareable frozen lab without changing the source directory:

```bash
eclab freeze -t lab.clab.yml --output demo.tar.gz
```

The archive contains a copied topology, a package lock and best-effort
wheelhouse, copied external VM images, and `run-eclab.sh`. It never includes
license files, pool paths, allocations, or clamp values. Pool-backed node
licenses become `__ECLAB_LICENSE_PROMPT__`, which asks the recipient for a
license file, pool directory, or `$VARIABLE` when the frozen lab is deployed.

Freeze copies the source lab while excluding managed state, virtual
environments, caches, and known license files. Add extra Git-ignore-style
patterns to `.eclab-freezeignore`; editions use `.<short-product>-freezeignore`.
Symlinks that point outside the source lab are rejected.
