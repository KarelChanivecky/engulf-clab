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
`PATH` is restored after the call, or during preparation unwind if a later plugin
cannot prepare the call. If another plugin stops preprocessing before the runtime
schema generator, the original failure remains authoritative and this plugin
suppresses the otherwise-secondary unused source-context warning.

## Sudo-less operation

Run `eclab sudoless` as the unprivileged user who needs Containerlab access.
The command resolves or provisions Containerlab using the same precedence above,
then uses `sudo` to:

1. create the system `clab_admins` group if it does not exist;
2. create the system `docker` group if it does not exist;
3. add the current user to both groups;
4. make the selected binary root-owned; and
5. set its mode to `4755` (root SUID, without group or world write access).

The command is safe to repeat. Do not run the wrapper itself with `sudo`; it
must identify the unprivileged account that should be added. Log out and back in
afterward so the login session obtains its new group membership. Confirm setup
with `ls -hal "$(command -v containerlab)"` and `groups`: the binary should be
root-owned with an `s` in the owner execute position, and the user should be in
both `clab_admins` and `docker`.

Membership in either `clab_admins` or `docker` grants effective root-level host
access through the corresponding tool. The command changes the selected binary
in place, including a binary in a configured or managed checkout. Rebuilding or
replacing that binary can clear its ownership or SUID bit; rerun
`eclab sudoless` after such a change. Package-managed Containerlab and Docker
installations normally create their respective groups, but the command remains
safe to repeat.

## Privileges and troubleshooting

The wrapper invokes privileged Containerlab operations with `sudo` when the
resolved executable lacks usable root SUID access. Run `eclab` as your normal
user; sudo authenticates the child operation. Help, completion and version
queries remain unprivileged. Sudo-less access is detected from binary ownership,
SUID mode, mount options and the caller's active `clab_admins` membership, so a
rebuilt binary automatically falls back to sudo until `eclab sudoless` is rerun.

Docker helpers independently use sudo for an inaccessible local Docker socket,
retaining the caller's endpoint and configuration. Managed WAN host commands
also invoke sudo, since Containerlab's SUID bit does not elevate plugins. A
missing or denied sudo command fails normally; automated invocations need
cached credentials or suitable sudoers authorization.

- Run `eclab --help` in the target environment and confirm
  `engulf_clab.ensure_containerlab` is active.
- Verify an explicit binary with `test -x` and a checkout with `go.mod`.
- Inspect `git status` when an update is refused; local changes are preserved.
- Reproduce a reported Go build from the checkout root when compilation fails,
  and verify the installed Go version and module dependencies.
- Preserve an invalid managed checkout for diagnosis or remove it intentionally
  when safe; it is not overwritten.
- If `eclab sudoless` fails, verify that `sudo`, `groupadd`, `usermod`, `chown`,
  and `chmod` are available through the host's root environment. A partially
  completed run is safe to repeat after correcting the reported failure.
- Under MCP, configure executable and checkout controls in the service profile;
  callers cannot override protected host paths.

## Runtime schema discovery

The schema generator prefers the contexts published here and uses a checkout's
existing `schemas/clab.schema.json` first.
