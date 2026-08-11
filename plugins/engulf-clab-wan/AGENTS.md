# Plugin Instructions

This directory contains the `engulf-clab-wan` plugin distribution.

## Purpose

The plugin adds Forticlab-style managed DHCP WAN bridge support to the
`engulf-clab` Containerlab wrapper.

It watches Containerlab calls for:

- `deploy`: before Containerlab runs, create/configure `FCLAB_DHCP_WAN` bridge
  nodes, start the packaged DHCP server, enable forwarding, and install NAT.
- `destroy`: after Containerlab exits successfully, stop DHCP, remove managed
  NAT rules, and delete bridges that the plugin created.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin import package: `engulf_clab_wan`
- Plugin ID: `dev.karel.engulf_clab.wan`

Plugin code imports `engulf_api`, not `engulf`.
It derives from `ExecutableWrapperPlugin` supplied by
`engulf_executable_wrapper_api`.

## Development Notes

- Keep the topology label contract compatible with Forticlab:
  `FCLAB_DHCP_WAN`, `FCLAB_DHCP_SUBNET`, `FCLAB_DHCP_GATEWAY`,
  `FCLAB_DHCP_POOL_START`, `FCLAB_DHCP_POOL_END`, `FCLAB_DHCP_DNS`,
  `FCLAB_DHCP_LEASE_TIME`, and `FCLAB_UPLINK_IF`.
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
- Do not create, read, migrate, or delete a topology-local `.forticlab/`
  directory. Existing Forticlab state belongs to Forticlab.
- DHCP is implemented by the packaged Python module. Do not add an external
  DHCP dependency such as `dnsmasq`.
- Do not run real bridge, iptables, or deploy/destroy operations unless the user
  explicitly asks. Prefer unit tests, YAML parsing, and dry import/discovery
  checks.
- Keep `analyze_call()` side-effect free. Host setup belongs in `prepare_call()`;
  post-destroy cleanup remains in `after_call()`.
