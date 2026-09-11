# Lab registry API

Install this package with `engulf-clab-lab-registry`. Consumers obtain the
invocation-bound `LabRegistry` through `lab_registry(api)`, call `records()` for
an immutable snapshot, and submit complete observations with `upsert()`.

`LabRecord` identifies a lab by its nonempty name and absolute canonical lab
directory. It optionally retains an absolute topology path, exact Docker image
IDs, and whether the lab has ever been observed as deployed. Upserts preserve a
known topology and deployment history while replacing image IDs with the newest
complete observation.

The API does not define persistence, perform discovery, or expose mutable state.
The registry handle is valid only for the current Engulf invocation. A missing
provider raises `LabRegistryError` with the package that must be installed.
