# Contributing

The package separates pure topology/allocation logic (`allocation.py`), host
observation (`host.py`), OS probe strategies (`probes.py`, `probe_linux.py`, and
`probe_windows.py`), versioned state (`registry.py`), and Engulf lifecycle
integration (`plugin.py`). The source topology is immutable; the plugin runs at
priority `-90` after current node-producing mutators and before the writer.

Use parser `EffectiveNode` snapshots for network-mode and kind/group selection.
Do not rebuild inheritance here; management addresses remain node-only.

`analyze_call()` validates only normalized options. `prepare_call()` reads the
final materialized node set, holds the allocator lease, inspects Docker and all
host route tables, runs bounded probes, records a pending claim, and adds
deferred topology edits. State transactions must never surround subprocesses.

`TraceStrategy` owns the per-address trace contract; `host.py` selects targets
and combines results without importing OS-specific APIs. The selector imports
only the running platform's implementation. Windows is an explicit stub.
Unavailable implementations or missing kernel features raise
`ProbeUnavailableError`. Availability probes are advisory: a response,
unavailable implementation, or probe failure logs a warning through the
callback-bound logger and never rejects a candidate. Keep Docker, route, and
claim checks authoritative.

The Linux strategy uses connected, nonblocking UDP sockets with `IP_RECVERR` or
`IPV6_RECVERR`. Decode the ICMP offender address from `sock_extended_err`, not
the quoted destination. Keep each trace within one deadline across all eight
hops, isolate concurrent traces through their ephemeral source ports, and close
sockets on every exit. Do not introduce raw sockets or an external trace tool.
Python 3.12/3.13 need the documented Linux UAPI socket-option values because
those versions do not expose the error-queue option constants.
Mock sockets, polling, and time in probe tests; never mutate host networking.

Preparation has two rollback paths. The inner `except BaseException` removes
this callback's pending claim while its lease is current. `prepare_failed()`
reacquires the lease after callback deactivation. Both restore inactive history
evicted by this attempt and leave unrelated active claims untouched.

Before allocation planning, reconcile active or uncertain claims whose recorded
workspace is no longer a directory. Keep pending claims and any claim with a
matching or unidentifiable Containerlab container. Remove a leftover management
network only when its Containerlab label, empty endpoint list, and recorded
subnet all match and no other reserved claim names it. Release registry rows
after network cleanup succeeds, then refresh host inventory. This preflight
must run before allocation checks so a later unrelated allocation error does
not leave dead workspaces consuming shared state.

After a wrapped process starts, a failed or interrupted deployment is uncertain
and remains reserved. A new attempt supersedes same-lab pending records as
uncertain before reserving its own claim, so late callbacks from the old attempt
cannot finalize the new one. A successful deployment promotes the pending claim
and retires the lab's prior allocation. Successful destroy marks claims inactive;
`--keep-mgmt-net` deliberately retains them.

Validate narrowly with:

```bash
.venv/bin/python -m pytest -q plugins/engulf-clab-sticky-ip/tests
.venv/bin/python -m compileall -q plugins/engulf-clab-sticky-ip/src
make build-engulf-clab-sticky-ip
make check-skill
```
