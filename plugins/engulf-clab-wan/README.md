# engulf-clab-wan

Creates Forticlab-style DHCP/NAT WAN bridges for marked Containerlab bridge
nodes. Install it with `python -m pip install engulf-clab-wan`, or through
`engulf-clab-all-plugins`. It changes host networking and therefore requires the
necessary Linux/Docker privileges.

## YAML configuration

Mark a bridge node with `FCLAB_DHCP_WAN`. The plugin removes its own control
labels from the generated topology before Containerlab receives it.

```yaml
topology:
  nodes:
    wan:
      kind: bridge
      labels:
        FCLAB_DHCP_WAN: "true"
        FCLAB_DHCP_SUBNET: "198.19.0.0/24"
        FCLAB_DHCP_GATEWAY: "198.19.0.1"
        FCLAB_DHCP_POOL_START: "198.19.0.100"
        FCLAB_DHCP_POOL_END: "198.19.0.200"
        FCLAB_DHCP_DNS: "1.1.1.1"
        FCLAB_DHCP_LEASE_TIME: "43200"
```

| Label | Meaning |
| --- | --- |
| `FCLAB_DHCP_WAN` | Required marker. Any truthy value enables the managed WAN. |
| `FCLAB_DHCP_SUBNET` | IPv4 subnet; default `198.19.0.0/24`. |
| `FCLAB_DHCP_GATEWAY` | Gateway address; default `198.19.0.1`. |
| `FCLAB_DHCP_POOL_START` / `FCLAB_DHCP_POOL_END` | DHCP pool bounds; defaults `.100` and `.200`. |
| `FCLAB_DHCP_DNS` | DHCP DNS server; default `1.1.1.1`. |
| `FCLAB_DHCP_LEASE_TIME` | DHCP lease seconds; default `43200`. |

| Invocation environment | Meaning |
| --- | --- |
| `FCLAB_UPLINK_IF` | Optional host uplink interface, bypassing automatic detection. |

## Lifecycle and cleanup

Before deploy, the plugin creates/configures the Linux bridge, gateway address,
DHCP server, IPv4 forwarding, and NAT towards the uplink. Resources are tracked
by canonical topology workspace and shared safely when more than one workspace
uses a bridge. Successful `destroy` releases the workspace claim;
`destroy -a` / `destroy --all` cleans all recorded WAN workspaces.

The plugin uses managed state for DHCP configuration, PID, leases, logs, and a
provisioning journal. It verifies owned processes and rules before cleanup and
rolls back failed provisioning. Do not manually delete its state while a WAN lab
is active.
