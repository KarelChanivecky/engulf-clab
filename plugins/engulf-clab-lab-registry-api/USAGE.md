# Lab registry API

Install this package with `engulf-clab-lab-registry`. Consumers obtain the
`LabRegistry` for the current invocation through `lab_registry(api)`, call
`records()` for an immutable snapshot, and submit complete observations with
`upsert()`. Both are in-memory operations that touch no Engulf capability, so
they are safe in any consumer callback.

`LabRecord` identifies a lab by its nonempty name and absolute canonical lab
directory. It optionally retains an absolute topology path, exact Docker image
IDs, and whether the lab has ever been observed as deployed. Upserts preserve a
known topology and deployment history while replacing image IDs with the newest
complete observation.

The API does not define persistence, perform discovery, or expose mutable state.
Implementations must hold records rather than an Engulf state handle, which is
valid only inside the callback that produced it; `upsert()` therefore records
intent that `engulf-clab-lab-registry` persists after the goal completes. The
value is valid only for the current Engulf invocation. A missing provider raises
`LabRegistryError` with the package that must be installed.
