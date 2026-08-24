# engulf-clab-ensure-containerlab

Ensures the `containerlab` executable is available for ordinary `engulf-clab`
calls. Install it with `python -m pip install engulf-clab-ensure-containerlab`,
or through `engulf-clab-all-plugins`. It has no topology fields. Every wrapped
Containerlab call checks that `docker` is available on `PATH` before continuing.

The plugin applies only when the executable-wrapper call targets the standard
`containerlab` binary. It does not change a custom wrapper binary. Provisioning
happens in `prepare_call()` after analysis succeeds, under a user-scoped
repository lease; help rendering and analysis remain side-effect free.
During `before_goal()`, the plugin publishes the same source selection without
cloning, updating, or building. After preparation it replaces that hint with
the exact resolved checkout or binary source for the schema generator.

## Resolution order

1. Executable path from `--eclab-containerlab-bin`.
2. Valid source checkout from `--eclab-containerlab-dir`; builds `bin/containerlab` when
   needed (requires Go).
3. `containerlab` found on `PATH`.
4. A managed user-state checkout cloned from the selected repository, then built.

| CLI option | Meaning |
| --- | --- |
| `--eclab-containerlab-bin PATH` | Explicit executable. It is never updated or rebuilt. |
| `--eclab-containerlab-dir DIR` | Existing source checkout. |
| `--eclab-containerlab-repo URL` | Clone source for a managed checkout; default is `https://github.com/KarelChanivecky/containerlab/tree/ft_fgt_license_support`. GitHub `/tree/<branch>` URLs are cloned at that branch. |
| `--eclab-containerlab-update` | Opt into a Git update check, at most daily per checkout. |
| `--eclab-containerlab-version REV` | Pin to a tag, commit, or Git revision; also enables checking. |

`CONTAINERLAB_BIN`, `CONTAINERLAB_DIR`, `CONTAINERLAB_REPO`,
`CONTAINERLAB_UPDATE`, and `CONTAINERLAB_VERSION` are supported environment
defaults suitable for shell profiles or service configuration. A matching CLI
option wins before source discovery, workspace resolution, and plugin
preparation.

On an update, the highest version-style release tag reachable from the branch is
preferred. A branch with no release tags fast-forwards by commit. Changed source
is rebuilt before invoking Containerlab. Non-Git directories, PATH binaries,
and `CONTAINERLAB_BIN` are untouched. Dirty Git worktrees are rejected rather
than reset.

Managed clones are staged before publication and protected by a user-scoped
lease. An invalid existing managed checkout is never overwritten.

## Checkout and build requirements

A valid source checkout is a directory containing `go.mod`. The plugin accepts
an executable `bin/containerlab` or top-level `containerlab`; if neither exists,
it requires `go` and runs:

```text
go build -o <checkout>/bin/containerlab .
```

The command runs without a shell from the checkout root. A changed Git revision
forces a rebuild; otherwise an existing executable is reused. `CONTAINERLAB_BIN`
must be an executable file and is never treated as a checkout. An invalid
configured binary or directory falls through to later resolution rather than
being executed.

Managed clones live in Engulf user state and are shared across workspaces. The
plugin never overwrites an invalid existing managed path, repairs a dirty
checkout, or mutates a non-Git checkout. Update/clamp behavior is implemented by
`engulf-clab-ensure-checkout`: it is opt-in, at most daily for the same request,
rejects dirty worktrees, prefers the highest reachable release-style tag, and
otherwise uses a fast-forward branch update.

## Invocation behavior

After resolving a binary, the plugin temporarily prepends its parent directory
to the process `PATH` so the wrapped executable lookup selects it. `after_call()`
restores the exact prior path. It does not persist an executable override in the
topology or workspace.

The `docker` prerequisite is checked even for an explicit Containerlab binary,
because ordinary Containerlab operation requires a container runtime. The
plugin does not install Docker, Go, Git, or operating-system packages.

## Troubleshooting

- Run `eclab --help` in the target environment and confirm
  `engulf_clab.ensure_containerlab` is active.
- Check `--eclab-containerlab-bin PATH` with `test -x`; check the selected
  checkout's `go.mod` and built executable when using the directory option.
- If a checkout update is rejected, inspect `git status`; the plugin will not
  discard local changes.
- If a build fails, run the reported Go build from the checkout and verify the
  installed Go version/module dependencies.
- If an old managed checkout is invalid, preserve it for diagnosis or remove it
  explicitly when safe; the plugin deliberately refuses to overwrite it.
- Under MCP, configure fixed Containerlab/eclab executable paths and checkout
  controls service-side. Caller overrides for these variables are rejected.

## Runtime schema discovery

The plugin records its provisioning variables and publishes a side-effect-free
source selection during `before_goal`. It publishes the resolved checkout or
binary again during preparation. The schema generator prefers these contexts
and uses a checkout's existing `schemas/clab.schema.json` first.
