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

Two properties describe the backing registry. `persistent` is true when the
file could be read and may be written; a destructive consumer must refuse to run
against a registry where it is false rather than act on an inventory it cannot
confirm or preserve. `revision` is the registry revision the session was loaded
from (`0` when unknown); compare it against a later commit to detect a
concurrent writer.

The API does not define persistence, perform discovery, or expose mutable state.
Implementations must hold records rather than an Engulf state handle, which is
valid only inside the callback that produced it; `upsert()` therefore records
intent that `engulf-clab-lab-registry` persists after the goal completes. The
value is valid only for the current Engulf invocation. A missing provider raises
`LabRegistryError` with the package that must be installed.

## Commit outcome

`engulf-clab-lab-registry` publishes a `RegistryCommit` under
`LAB_REGISTRY_COMMIT_CONTEXT` from its `after_goal`. Read it from a callback that
ordered itself to run later in the same phase — as `engulf-clab-reclaim` does —
to learn whether recorded intent reached durable storage before you act on it.

`committed` is false when nothing could be written; no destructive step may run
then. `revision` is the revision in effect afterwards, so a value above the
revision your plan was based on means the registry moved and the plan needs
re-validation. `records` is the complete stored inventory when it is known, and
`error` explains a failure. The value is immutable and valid only for the
current invocation.
