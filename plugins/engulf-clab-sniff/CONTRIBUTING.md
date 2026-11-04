# Contributing to engulf-clab-sniff

`plugin.py` owns schema declaration, help, completion registration, and
`before_goal` preemption. `arguments.py` is the single source for the tcpdump
allowlist and validates every token before process construction. `topology.py`
maps declared link endpoints to direct peers and paired interface names.
`docker.py`
owns read-only container discovery. `command.py` creates an optional private
pcap path and runs the disposable helper. For Wireshark it stages a private,
temporary extcap interface and capture plan; `extcap.py` implements interface
discovery, pcap delivery, capture-filter validation, and stop cleanup.

The adapter runs at priority 200, records its schema before preempting `sniff`,
and reads/writes only `SCHEMA_CONTEXTS`; it does not depend on an invocation
topology session. Packaging orders it after the schema compiler and lab parser
plugins.

Keep these invariants:

- Complete topology nodes and direct neighbors from YAML only; show both
  endpoint interface names for each suggested link. Completion must not require
  Docker or mutate files.
- Match the node to Containerlab labels and require it to be running before
  starting capture.
- Select the NODE1-side interface from the direct link; reject ambiguous pairs
  unless `--interface` names one of those endpoints.
- Use argv lists only. Never invoke a shell or pass unknown tcpdump switches.
  The allowlist must continue to exclude interface overrides, arbitrary input
  or output files, filter-file reads, and command hooks.
- Keep `--write` as the only file-output route: exclusive creation, private
  permissions, pcap streaming through Docker stdout, and no host mount or
  overwrite.
- Route Wireshark through extcap so its Stop and Restart controls own the
  helper lifecycle. The extcap must forward stop signals to `docker run`, wait
  for container cleanup, and write only pcap bytes to Wireshark's FIFO. Drain
  helper stderr without forwarding normal Docker/tcpdump status; surface its
  bounded diagnostic tail only when the helper exits unsuccessfully.
- Keep the per-invocation extcap plan private and temporary. Do not install a
  persistent Wireshark helper or pass user-controlled shell text to a process.
- Validate any capture filter received from Wireshark with the same tcpdump
  allowlist before adding it to the helper argv.
- Treat Wireshark as an optional host executable required only for
  `--wireshark`. Declare `wireshark` and `dumpcap` as option-level host tools
  on that flag, not command-wide requirements. Do not pass caller-controlled
  Wireshark flags or combine the mode with the plugin's `--write` output.
- `sudoless` is owned and preempted by `engulf_clab.ensure_containerlab`.
  Declare this plugin before it in packaging so this plugin can add the current
  user to an already configured capture group first, then return `None` so the
  Containerlab setup continues. Never change the `dumpcap` binary or grant new
  capture capabilities; if its package has no safe group-execution setup, give
  the operator manual package-configuration guidance.
- Run with a disposable helper, container network namespace sharing, all
  capabilities dropped except `NET_RAW`, and no Docker socket mount.
- Declare schema/compiler ordering and plugin dependencies in packaging. Do not
  add privileged-goal entry points; eclab is an unprivileged wrapper.
- Keep `USAGE.md`, the schema reference snapshot, dynamic help, and completion
  aligned with the supported command and argument grammar.

Narrow validation commands:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-sniff/src
.venv/bin/python -m build --no-isolation plugins/engulf-clab-sniff
```
