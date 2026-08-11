# engulf-clab-ensure-containerlab

`engulf-clab-ensure-containerlab` ensures that normal `engulf-clab` calls can
execute Containerlab. It resolves an executable in this order:

1. An executable `CONTAINERLAB_BIN`.
2. A valid `CONTAINERLAB_DIR` source checkout, building `bin/containerlab` when
   necessary.
3. `containerlab` on `PATH`.
4. A managed user-scoped checkout cloned from `CONTAINERLAB_REPO`, then built.

`CONTAINERLAB_REPO` defaults to
`https://github.com/srl-labs/containerlab.git`. An existing invalid managed
checkout is never overwritten. The checkout is protected by a user-scoped
lease and cloned into a temporary sibling before it is published.

The plugin temporarily adds the resolved executable directory to `PATH` for
the wrapped normal call, then restores the process environment afterwards.
