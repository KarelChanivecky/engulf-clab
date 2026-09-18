# Host command execution

Install `engulf-host-exec` in the caller's Python environment. Consumers depend
on it directly; it has no activation command, topology controls, edition prefix,
persistent state, or resource leases.

`root_command(argv, non_interactive=False, background=False, preserve_env=())` returns the argv
for a privileged child: direct for root, otherwise `sudo -- <absolute-executable>`.
Sudo handles authentication on the terminal and enforces the host sudoers policy.
Missing tools raise `FileNotFoundError`; callers handle child failures normally.
Use `require_root_access()` before launching detached or parallel privileged work.
For detached sudo children, use `background=True` (`sudo -b`) and keep the
caller's terminal session until sudo authenticates. Starting sudo itself in a
new session loses tty-scoped cached credentials. Already-root callers are
responsible for detaching their direct child.

`docker_command(argv)` accepts a Docker command starting with its executable.
It checks the endpoint selected by `DOCKER_CONTEXT`, `DOCKER_HOST`, or the user's
current context in `DOCKER_CONFIG` (default `~/.docker`). Only an inaccessible
local Unix socket selects sudo. Accessible sockets, rootless setups, remote
endpoints and already-root callers execute directly. A missing socket or unknown
context is left to Docker to diagnose. Consumers pass Docker subcommands, not
global endpoint overrides; select the endpoint through Docker's environment or
current context. Sudo preserves Docker variables and passes the original config
directory explicitly, including its registry credentials and TLS configuration.
`python -m engulf_host_exec <docker arguments>` exposes the same behavior to
packaged shell launchers without a separate Docker executable shim installation.

`docker_environment()` supplies a temporary child environment for Make recipes.
Only their Docker invocations use sudo; source files and build staging stay owned
by the caller. It cleans its private shim directory on success or failure.

No sudoers changes are made. Noninteractive users must have cached credentials
or command authorization in sudoers. A denied sudo command fails normally.
Privilege belongs to each selected child, never to the parent application.
