# engulf-clab-ensure-containerlab

Ensures a `containerlab` executable is available for ordinary eclab calls. It
applies only to the standard Containerlab wrapper and has no topology fields. It
requires `docker` on `PATH` and does not install Docker, Git, Go, or
operating-system packages. The `docker` prerequisite is checked even for an
explicit Containerlab binary, because ordinary Containerlab operation requires a
container runtime.

Install with `python -m pip install engulf-clab-ensure-containerlab`, or through
`engulf-clab-all-plugins`.

## Resolution

Sources are tried in this order:

1. executable from `--eclab-containerlab-bin`;
2. checkout from `--eclab-containerlab-dir`, building it when necessary;
3. `containerlab` already on `PATH`;
4. a managed user-state checkout cloned from the selected repository.

| CLI option | Persistent default | Meaning |
| --- | --- | --- |
| `--eclab-containerlab-bin PATH` | `CONTAINERLAB_BIN` | Explicit executable; never updated or rebuilt. |
| `--eclab-containerlab-dir DIR` | `CONTAINERLAB_DIR` | Existing source checkout. |
| `--eclab-containerlab-repo URL` | `CONTAINERLAB_REPO` | Managed clone source; defaults to `https://github.com/KarelChanivecky/containerlab/tree/ft_fgt_license_support`. GitHub `/tree/<branch>` URLs select that branch. |
| `--eclab-containerlab-update` | `CONTAINERLAB_UPDATE` | Opt into an update check, at most daily per checkout/request. |
| `--eclab-containerlab-version REV` | `CONTAINERLAB_VERSION` | Pin a tag, commit, or revision and enable checking. |

A matching CLI option wins before source discovery, workspace resolution, and
plugin preparation, ahead of its environment default. `CONTAINERLAB_BIN` must be
an executable file and is never treated as a checkout. Invalid explicit values
fall through to later sources rather than being executed.

## Managed checkout

A valid checkout contains `go.mod`. An executable `bin/containerlab` or
top-level `containerlab` is reused; otherwise the plugin requires Go and runs
`go build -o <checkout>/bin/containerlab .` from the checkout root, without a
shell. A changed
Git revision forces a rebuild.

Managed clones are staged before publication and shared across workspaces.
Update/version controls apply to clean configured Git checkouts as well as the
managed checkout. Update selects the highest reachable version-shaped tag, or
fast-forwards the branch when none exists. A version clamp must resolve to a
commit and is checked out detached. A checkout without an origin remains at its
current revision. Dirty worktrees are rejected rather than reset. Explicit
binaries, `PATH` binaries, non-Git directories, and invalid existing managed
paths are never overwritten or repaired automatically.

The resolved binary is selected only for the current invocation; the previous
`PATH` is restored afterward.

## Privileges and troubleshooting

This plugin resolves the executable but does not grant the host privileges
Containerlab needs. Depending on the node kinds and host setup, local deploy
may require root or Containerlab's documented sudo-less configuration. Managed
WAN bridges have their own explicit root requirement; ordinary labs can still
fail for separate Docker or Containerlab privilege reasons.

- Run `eclab --help` in the target environment and confirm
  `engulf_clab.ensure_containerlab` is active.
- Verify an explicit binary with `test -x` and a checkout with `go.mod`.
- Inspect `git status` when an update is refused; local changes are preserved.
- Reproduce a reported Go build from the checkout root when compilation fails,
  and verify the installed Go version and module dependencies.
- Preserve an invalid managed checkout for diagnosis or remove it intentionally
  when safe; it is not overwritten.
- Under MCP, configure executable and checkout controls in the service profile;
  callers cannot override protected host paths.

## Runtime schema discovery

The schema generator prefers the contexts published here and uses a checkout's
existing `schemas/clab.schema.json` first.
