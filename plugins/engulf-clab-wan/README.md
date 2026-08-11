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
uplink. After a successful `engulf-clab destroy`, it removes that workspace's
claim. Host resources remain until their final workspace claim is removed. A
successful `destroy -a` or `destroy --all` cleans every WAN workspace recorded in
Engulf's state catalog.

Workspace state stores only bridge claims. A user-scoped registry owns the shared
bridge configuration, workspace references, provisioning journal, DHCP runtime
files, and the original IPv4-forwarding setting. The plugin leases each bridge
before host mutation, adds an ownership comment to every iptables rule, and only
removes gateway addresses or bridges that it created. `engulf-clab` uses the
topology directory as the canonical workspace, including when `--topo` names a
topology outside the current directory. The plugin does not create a
`.forticlab/` directory.

The detached DHCP server uses managed user-state paths for its configuration, PID,
leases, and log. Its PID is verified against the managed configuration before it
is stopped. Failed provisioning records completed actions in a journal and rolls
them back; an interrupted attempt is recovered before a later deploy of the same
bridge.

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
