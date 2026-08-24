# Plugin Instructions

This directory contains the `engulf-clab-wan` plugin distribution.

## Purpose

The plugin adds managed DHCP WAN bridge support to the `engulf-clab`
Containerlab wrapper, using a fixed `ECLAB` label prefix shared by every
edition.

It watches Containerlab calls for:

- `deploy`: before Containerlab runs, create/configure `ECLAB_DHCP_WAN` bridge
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
- Keep runtime help, README label/default tables, mismatched-prefix rejection,
  uplink selection, resource ownership, and cleanup semantics synchronized.
- Run topology, registry, state, plugin, and Engulf integration tests. Mock
  effective UID and every `ip`/`iptables`/`sysctl`/process operation; never
  mutate real host networking in automated tests.
- Build/install the wheel with parser/writer and inspect the fixed-prefix help.
  Keep every WAN label in `PLUGIN_SCHEMA` and run `make check-skill`.
