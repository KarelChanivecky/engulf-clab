# engulf-clab-wan

`engulf-clab-wan` adds Forticlab-style managed DHCP WAN bridges to the
`engulf-clab` Containerlab wrapper.

Mark a Containerlab bridge node with `FCLAB_DHCP_WAN`:

```yaml
topology:
  nodes:
    wan:
      kind: bridge
      labels:
        FCLAB_DHCP_WAN: "true"
```

Before `engulf-clab deploy` runs Containerlab, the plugin creates/configures the
host Linux bridge, assigns the gateway address, starts a packaged Python DHCP
server, enables IPv4 forwarding, and installs iptables NAT toward the host
uplink. After a successful `engulf-clab destroy`, it removes the plugin-managed
runtime resources.

Runtime state is stored next to the topology in `.forticlab/` for compatibility
with existing Forticlab-managed labs.

Optional labels:

```yaml
labels:
  FCLAB_DHCP_WAN: "true"
  FCLAB_DHCP_SUBNET: "198.19.0.0/24"
  FCLAB_DHCP_GATEWAY: "198.19.0.1"
  FCLAB_DHCP_POOL_START: "198.19.0.100"
  FCLAB_DHCP_POOL_END: "198.19.0.200"
  FCLAB_DHCP_DNS: "1.1.1.1"
  FCLAB_DHCP_LEASE_TIME: "43200"
```

Override host uplink detection with `FCLAB_UPLINK_IF`.
