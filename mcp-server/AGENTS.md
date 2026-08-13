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
