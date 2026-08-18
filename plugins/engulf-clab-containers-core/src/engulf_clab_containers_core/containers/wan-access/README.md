# eclab.containers/wan-access

The WAN access container forwards IPv4 traffic from one lab-facing interface
through Containerlab management `eth0` and masquerades it there. DHCP is
optional: with no supported `ECLAB_DHCP_*` variable, the container provides NAT
only and the lab configures static addresses; setting any supported DHCP
variable also assigns the gateway address and starts a DHCP server.

It is not a VPN, application proxy, DNS resolver, or SSH endpoint. It accepts
forwarded traffic without client authentication or additional filtering.

## Interface model

The recipe requires Containerlab management networking and exactly one
lab-facing link:

- `eth0` is management-facing, carries the container's default route, and is
  the masquerade uplink; and
- the single other discovered interface is lab-facing and receives forwarded
  traffic. DHCP mode also assigns its configured gateway address there.

Connecting zero or more than one lab-facing link makes the container exit
unhealthy; attach exactly one.

## Static NAT example

With no `ECLAB_DHCP_*` variables, use normal Containerlab configuration to
assign the data-plane addresses and routes:

```yaml
name: static-wan-demo

topology:
  nodes:
    wan:
      image: eclab.containers/wan-access
      exec:
        - ip address replace 198.19.0.1/24 dev eth1
    client:
      kind: linux
      image: example/client:latest
      exec:
        - ip address replace 198.19.0.2/24 dev eth1
        - ip route replace default via 198.19.0.1 dev eth1
  links:
    - endpoints: ["wan:eth1", "client:eth1"]
```

The runtime brings the lab interface up and installs NAT before Containerlab
runs node `exec` commands. It does not infer or assign a static gateway address.

## Optional DHCP

Setting any variable in this table enables DHCP. Unset fields then use their
defaults.

| Variable | Meaning | Default |
| --- | --- | --- |
| `ECLAB_DHCP_SUBNET` | IPv4 CIDR subnet assigned to the lab interface | `198.19.0.0/24` |
| `ECLAB_DHCP_GATEWAY` | Gateway address, inside the subnet and outside the pool | `198.19.0.1` |
| `ECLAB_DHCP_POOL_START` / `ECLAB_DHCP_POOL_END` | DHCP pool bounds, inside the subnet | `198.19.0.100` / `198.19.0.200` |
| `ECLAB_DHCP_DNS` | DNS server handed out to clients | `1.1.1.1` |
| `ECLAB_DHCP_LEASE_TIME` | Lease seconds | `43200` |

The gateway and both pool bounds must lie inside the subnet, the gateway must
fall outside the pool, and pool start must not exceed pool end. Invalid values
make the container exit unhealthy before DHCP starts.

```yaml
name: dhcp-wan-demo

topology:
  nodes:
    wan:
      image: eclab.containers/wan-access
      env:
        ECLAB_DHCP_SUBNET: "198.19.0.0/24"
        ECLAB_DHCP_GATEWAY: "198.19.0.1"
        ECLAB_DHCP_POOL_START: "198.19.0.100"
        ECLAB_DHCP_POOL_END: "198.19.0.200"
    client:
      kind: linux
      image: example/client:latest
      exec:
        - udhcpc -i eth1
  links:
    - endpoints: ["wan:eth1", "client:eth1"]
```

The client must request DHCP itself. The collection manager injects Linux kind,
`image-pull-policy: Never`, `NET_ADMIN`, IPv4 forwarding, and the package build
recipe. Do not override those required values.

## Runtime, health, and lifecycle

The entrypoint waits for exactly one lab-facing interface, brings it up, and
installs `ECLAB_WAN_ACCESS_NAT` (POSTROUTING masquerade toward `eth0`) plus
`ECLAB_WAN_ACCESS_FORWARD` (forwarding between the lab interface and `eth0`).
These rules are installed in both static and DHCP modes.

When DHCP is enabled, the runtime validates its configuration, assigns the
gateway address, and runs `dnsmasq` bound to the lab interface with DNS
resolution disabled (`--port=0`). It then creates
`/run/eclab-wan-access.ready`. In static mode it creates the same marker after
NAT setup and remains alive while Containerlab applies any `exec` configuration.

All rules, addresses, and processes remain inside the container network
namespace. Destroying the node removes them. The recipe owns no host state,
Engulf state, volumes, or after-destroy cleanup; its local image remains cached.

## Security and troubleshooting

The container forwards any traffic received on its lab interface toward
`eth0`. DHCP mode also grants leases without authenticating clients. Rely on
lab and host firewalls for additional policy, and do not use it to bypass an
authorization boundary.

For diagnosis:

1. Run `eclab --eclab-containers-help` and confirm
   `eclab.containers/wan-access` is active.
2. Inspect `docker logs clab-<lab>-<node>` and Docker health.
3. Confirm the node has `eth0` plus exactly one lab interface. Use a full
   redeploy when a plain Docker restart has lost Containerlab veth links.
4. In static mode, confirm the lab assigned addresses and routes and did not
   accidentally set an `ECLAB_DHCP_*` variable.
5. In DHCP mode, confirm the client issues a request on its attached interface.
6. Inspect `ip address`, `ECLAB_WAN_ACCESS_NAT`, and
   `ECLAB_WAN_ACCESS_FORWARD` inside the container, then verify `eth0`
   reachability before testing client egress.
