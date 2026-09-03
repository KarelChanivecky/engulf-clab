# Freeze contributor API

Install this package alongside `engulf-clab-freeze`. A contributor publishes one
object in the `engulf_clab.freeze.v1` entry-point group. Its entry-point name must
equal its globally unique `contributor_id`.

Contributors may add only namespaced command flags, sanitize staged files, add
authenticated format-2 metadata, resolve recipient bindings during defrost, and
restore state into the unpublished staging directory. Hooks must not alter the
source lab or publish outside the paths supplied in their context.
