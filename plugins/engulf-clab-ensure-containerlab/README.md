# engulf-clab-ensure-containerlab

Ensures the `containerlab` executable is available for ordinary `engulf-clab`
calls. Install it with `python -m pip install engulf-clab-ensure-containerlab`,
or through `engulf-clab-all-plugins`. It has no topology fields. Every wrapped
Containerlab call checks that `docker` is available on `PATH` before continuing.

## Resolution order

1. Executable path in `CONTAINERLAB_BIN`.
2. Valid source checkout in `CONTAINERLAB_DIR`; builds `bin/containerlab` when
   needed (requires Go).
3. `containerlab` found on `PATH`.
4. A managed user-state checkout cloned from `CONTAINERLAB_REPO`, then built.

| Environment variable | Meaning |
| --- | --- |
| `CONTAINERLAB_BIN` | Explicit executable. It is never updated or rebuilt. |
| `CONTAINERLAB_DIR` | Existing source checkout. |
| `CONTAINERLAB_REPO` | Clone source for a managed checkout; default is `https://github.com/srl-labs/containerlab.git`. |
| `CONTAINERLAB_UPDATE=1` | Opt into a Git update check, at most daily per checkout. |
| `CONTAINERLAB_VERSION` | Pin to a tag, commit, or Git revision; also enables checking. |

On an update, the highest version-style release tag reachable from the branch is
preferred. A branch with no release tags fast-forwards by commit. Changed source
is rebuilt before invoking Containerlab. Non-Git directories, PATH binaries,
and `CONTAINERLAB_BIN` are untouched. Dirty Git worktrees are rejected rather
than reset.

Managed clones are staged before publication and protected by a user-scoped
lease. An invalid existing managed checkout is never overwritten.
