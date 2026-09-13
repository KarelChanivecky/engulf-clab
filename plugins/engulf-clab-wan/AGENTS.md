# Plugin Instructions

This directory contains the `engulf-clab-wan` plugin distribution.

## Purpose

The plugin adds managed DHCP WAN bridge support to the `engulf-clab`
Containerlab wrapper, using a fixed `ECLAB` label prefix shared by every
edition.

It watches Containerlab calls for:

- `deploy` and single-source `redeploy`: before Containerlab runs, create/configure `ECLAB_DHCP_WAN` bridge
  nodes, start the packaged DHCP server, enable forwarding, and install NAT.
- `destroy`: after Containerlab exits successfully, stop DHCP, remove managed
  NAT rules, and delete bridges that the plugin created.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin import package: `engulf_clab_wan`
- Plugin ID: `engulf_clab.wan`

Plugin code imports `engulf_api`, not `engulf`. It derives from
`SchemaBackedPlugin`, which remains an executable-wrapper plugin adapter.

## Development Notes

- Keep `--eclab-uplink-interface` bound to persistent `ECLAB_UPLINK_IF` and
  thread the normalized event environment into uplink detection. WAN node
  labels remain topology controls, not wrapper options.
- Use the fixed `ECLAB` label prefix (`networks.LABEL_PREFIX`) for every DHCP
  WAN label and for `ECLAB_UPLINK_IF`. Do not derive it from
  `api.application.short_product_name`/`product` — labels must stay portable
  across editions, unlike topology-local state (see below). Reject any
  `_DHCP_*`-suffixed label using another prefix instead of silently ignoring
  it.
- Use `StateScope.WORKSPACE` only for a workspace's bridge claims. The
  user-scoped state store owns the host-resource registry, DHCP process files,
  provisioning journal, and forwarding ownership record.
- Acquire all `wan-bridge:<name>` leases (and the IPv4-forwarding lease) before
  mutating host resources. Use short transactions for registry updates; never
  hold a state transaction while running host commands.
- Use Engulf's managed `exists`, `read_text`, `write_text`, and `delete`
  operations for metadata and configuration. Use `path()` only to give the
  detached DHCP process access to its configuration, PID, lease, and log files.
- Successful ordinary destroy removes the current workspace claim. Only the last
  claim may stop DHCP, remove marked rules, and delete a plugin-created bridge.
  Successful `destroy -a` or `destroy --all` must attempt every workspace
  returned by `api.known_workspaces()`.
- Keep iptables ownership comments, exact-address ownership, DHCP PID identity
  checks, and the provisioning journal. These are required for safe recovery
  after a failed host operation.
- DHCP is implemented by the packaged Python module. Do not add an external
  DHCP dependency such as `dnsmasq`.
- Do not run real bridge, iptables, or deploy/destroy operations unless the user
  explicitly asks. Prefer unit tests, YAML parsing, and dry import/discovery
  checks.
- Keep `analyze_call()` side-effect free. Host setup belongs in `prepare_call()`;
  post-destroy cleanup remains in `after_call()`.
- Declare the parser, writer, and schema ordering edges only in the
  `engulf.plugins.v1.dependency.engulf_clab_wan` package metadata. Do not
  restore `plugin_dependencies` on the class; Engulf 0.2 rejects code-declared
  dependencies.
- `prepare_call()` claims real host bridges, so both failure paths must release
  them. Release only the claims this invocation added: record the workspace's
  pre-existing claims before setup, release the difference, and restore the
  retained set. A redeploy over a live lab must never tear down bridges its
  previous successful deploy still owns.
- `prepare_failed()` handles a later plugin failing. The goal never dispatches it
  to the plugin that raised, so `_setup_before_deploy()` also catches
  `BaseException` and releases its own partial claims before re-raising. Keep
  both paths; neither covers the other's case.
- That in-`prepare_call()` release runs while the bridge leases are still held,
  because the callback has not been deactivated yet. Call `_release_claims()`
  there, never `_rollback_deploy()`: acquiring raises a nested-lease
  `RuntimeError` that would replace the real provisioning failure in the
  diagnostics. `prepare_failed()` runs after deactivation released those leases,
  so it takes them again through `_rollback_deploy()`. The split is required, not
  cosmetic.
- An interrupt now unwinds preparation exactly as an exception does, so a bridge
  claimed here is released when a *later* plugin is interrupted. This plugin's own
  interrupt is still its own: that is what the `except BaseException` handler in
  `_setup_before_deploy()` covers, and why it must not narrow to `Exception`.
  Keep it a failure handler rather than `finally` — `_record_claims()` runs on
  both paths, but the release must not. Keep the registry journal working
  regardless; it is what recovers a bridge caught mid-provisioning on the next
  deploy.
- Use `release_workspace_bridges()` for unwind and `cleanup_dhcp_wan_bridges()`
  for destroy. Only the destroy path may call `WorkspaceState.destroy()`;
  unwind keeps the workspace state a previous deploy still owns.
- `setup_dhcp_wan_bridges()` records each workspace claim as it is made. Keep
  that incremental write: a bridge failing midway through the loop must still
  leave the already-claimed bridges recoverable by destroy and unwind.
- Keep runtime help, `USAGE.md` label/default tables, mismatched-prefix rejection,
  uplink selection, resource ownership, and cleanup semantics synchronized.
- Run topology, registry, state, plugin, and Engulf integration tests. Mock
  effective UID and every `ip`/`iptables`/`sysctl`/process operation; never
  mutate real host networking in automated tests.
- Build/install the wheel with parser/writer and inspect the fixed-prefix help.
  Keep every WAN label in `PLUGIN_SCHEMA` and run `make check-skill`.
