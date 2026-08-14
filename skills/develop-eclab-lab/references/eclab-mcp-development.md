# MCP Server Instructions

`engulf-clab-mcp` is a separately publishable local-control service. Keep its
privilege boundary explicit:

- `eclab-mcp` is an unprivileged MCP stdio bridge.
- `eclab-mcpd` is the root-owned executor and accepts only versioned local RPC
  over its Unix socket.
- Never add a TCP listener, shell execution, arbitrary Containerlab flags,
  arbitrary topology paths, or an arbitrary environment pass-through.
- Resolve every topology through a configured lab root and use fixed executable
  argument vectors. Do not log profile secrets or caller environment values.
- Keep daemon state and job logs independent of the wrapper and plugin package
  distributions. The daemon invokes the installed `eclab` command as a child.

The systemd unit is intentionally conservative: test it in a disposable local
setup before tightening service sandboxing, because Containerlab and Docker need
access to configured lab roots and the Docker daemon.

## Configuration and Filesystem Invariants

- Require an absolute, regular, non-symlink configuration path. When effective
  UID is root, require root ownership and mode `0600`.
- Require absolute executable paths and existing non-symlink lab-root
  directories. Do not search a caller-controlled `PATH` for privileged tools.
- Treat stable lab IDs as opaque. Resolve them only by comparing against fresh
  discovery results; never decode a client string into a filesystem path.
- Keep topology reads bounded, skip state/build directories, do not follow
  directory symlinks, and return safe errors without host paths.
- Apply the service-controlled base environment last. Keep loader, language
  runtime, package-manager, Git/SSH, Docker, Containerlab, Engulf, XDG, and
  service controls outside caller authority.
- License-pool and topology-referenced VM-source variables are profile-owned
  even when their names are otherwise ordinary application variables.

## RPC and Job Invariants

- Keep the private RPC protocol versioned, newline framed, and bounded. One
  connection handles one request. Reject unknown methods and extra parameters.
- MCP tool results must use structured `ok/result` or `ok/error` objects and
  stable safe error codes. Do not expose internal exceptions.
- Deploy and destroy construct only fixed whole-lab argv and remain
  asynchronous. Preserve one active lifecycle job per lab and return its ID on
  conflict.
- Store only audit-safe metadata. Never persist or log command environments,
  secrets, or raw argv that may contain sensitive values.
- Bound synchronous stdout/stderr and job logs while continuing to drain child
  pipes. Bound log-tail line counts and list sizes.
- Start children in their own process group. Cancellation may signal only the
  known job group and may force-kill it only after the configured grace period.
- On restart, mark interrupted active records failed; never silently resume
  privileged work.

## Tool Semantics

- `eclab_validate` is read-only base Containerlab validation. Keep it on the
  fixed Containerlab binary and offline graph path; do not turn it into deploy.
- `eclab_diagnostics`, status, and logs remain bounded read-only operations.
- Node logs may target only a node declared by the resolved topology and mapped
  through current inspection. Do not accept arbitrary container names.
- Destroy always targets exactly one discovered topology. Do not expose
  `destroy --all`, node filters, or pass-through flags.

## Documentation and Validation

- Keep `README.md`, `etc/eclab-mcp/config.toml.example`, installer help, MCP tool
  docstrings, and configuration defaults/ranges synchronized.
- When adding a configuration key, update the dataclass, parser validation,
  example TOML, guided installer, README settings table, and tests together.
- When changing a tool, update bridge schema/docstrings, daemon dispatch, RPC
  validation, operation behavior, README tool table/workflow, and tests.
- Run the complete MCP suite for security, protocol, catalog, job, configuration,
  installer, or operation changes:

```bash
.venv/bin/python -m pytest -q mcp-server/tests
.venv/bin/python -m compileall -q mcp-server/src
.venv/bin/python -m build --no-isolation mcp-server
```

- Use temporary directories, fake executables, and mocked subprocesses in unit
  tests. Do not install/restart the system service or run real lab lifecycle
  operations unless explicitly authorized.
- After README or behavior changes, regenerate the packaged skill reference and
  use `Skill-Impact: updated` when committing it.
