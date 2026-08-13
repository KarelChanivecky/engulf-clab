# engulf-clab-containers-core

Core collection plugin `eclab.containers`. It currently provides
`eclab.containers/host-connector:latest`.

```yaml
topology:
  nodes:
    outside-vm:
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
        ECLAB_CONNECT_HOST_2: "2001:db8:10::50;2001:db8:20::50"
  links:
    - endpoints: ["router:eth1", "outside-vm:eth1"]
```

`eth0` is the Containerlab management interface and must be able to route to
the external targets. Every interface other than `eth0` is automatically
treated as lab-facing, and every declared VIP is made available on each of
those interfaces. Separate lab links remain isolated: reply traffic is steered
back through the interface where its connection arrived.

Each mapping exposes all protocols and ports of the external IP through the
VIP; for example, SSH to the VIP reaches SSH on the external host. Source NAT
means the external host sees the connector's management address. The lab needs
no WAN bridge or DHCP service, but the connector's management network must have
a route to each external target.

`ECLAB_CONNECT_HOST` and `ECLAB_CONNECT_HOST_0` are aliases and cannot be used
together. Numbered mappings may be sparse (`_2`, `_7`, and so on). A VIP and
target must use the same address family; both IPv4 and IPv6 mappings are
supported by one node.
