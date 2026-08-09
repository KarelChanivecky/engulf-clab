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

- Plugin entry point group: `engulf.plugins.v1.engulf_clab`
- Plugin import package: `engulf_clab_wan`
- Plugin ID: `dev.karel.engulf_clab.wan`

Plugin code imports `engulf_api`, not `engulf`.

## Development Notes

- Keep the topology label contract compatible with Forticlab:
  `FCLAB_DHCP_WAN`, `FCLAB_DHCP_SUBNET`, `FCLAB_DHCP_GATEWAY`,
  `FCLAB_DHCP_POOL_START`, `FCLAB_DHCP_POOL_END`, `FCLAB_DHCP_DNS`,
  `FCLAB_DHCP_LEASE_TIME`, and `FCLAB_UPLINK_IF`.
- Runtime state belongs next to the topology in `.forticlab/` for compatibility
  with existing labs.
- DHCP is implemented by the packaged Python module. Do not add an external
  DHCP dependency such as `dnsmasq`.
- Do not run real bridge, iptables, or deploy/destroy operations unless the user
  explicitly asks. Prefer unit tests, YAML parsing, and dry import/discovery
  checks.
