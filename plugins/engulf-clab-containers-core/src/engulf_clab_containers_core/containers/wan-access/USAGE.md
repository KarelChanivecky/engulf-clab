# eclab.containers/wan-access

The WAN access container forwards IPv4 traffic from one lab-facing interface
through management `eth0` and masquerades it there. With no supported
`ECLAB_DHCP_*` value it provides NAT only; setting any supported DHCP value
also assigns a gateway and starts DHCP. It is not a VPN, proxy, DNS resolver,
or SSH endpoint and does not authenticate forwarded clients.

## Interface model

The recipe requires Containerlab management networking and exactly one
lab-facing link. `eth0` carries the container's default route and is the
masquerade uplink. The single other interface is lab-facing. Zero or more than
one lab-facing interface makes the container unhealthy.

For static addressing, omit every `ECLAB_DHCP_*` value and configure the data
plane normally:

```yaml
name: static-wan-demo
topology:
  nodes:
    wan:
      kind: linux
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
runs node `exec` commands, so the addressing above is applied on top of a
working data plane. It does not infer a static gateway address. In static mode
it creates its readiness marker after NAT setup and stays alive while
Containerlab applies any `exec` configuration.

## Optional DHCP

Setting any variable below enables DHCP; omitted values use these defaults:

| Variable | Meaning | Default |
| --- | --- | --- |
| `ECLAB_DHCP_SUBNET` | IPv4 subnet | `198.19.0.0/24` |
| `ECLAB_DHCP_GATEWAY` | Gateway inside the subnet and outside the pool | `198.19.0.1` |
| `ECLAB_DHCP_POOL_START` / `ECLAB_DHCP_POOL_END` | Pool bounds inside the subnet | `198.19.0.100` / `198.19.0.200` |
| `ECLAB_DHCP_DNS` | DNS server advertised to clients | `1.1.1.1` |
| `ECLAB_DHCP_LEASE_TIME` | Lease seconds | `43200` |

The gateway and both pool bounds must be inside the subnet, pool start must not
exceed pool end, and the gateway must be outside the pool. Invalid values make
the container exit unhealthy before DHCP starts.

```yaml
name: dhcp-wan-demo
topology:
  nodes:
    wan:
      kind: linux
      image: eclab.containers/wan-access
      env:
        ECLAB_DHCP_SUBNET: "198.19.0.0/24"
    client:
      kind: linux
      image: example/client:latest
      exec:
        - udhcpc -i eth1
  links:
    - endpoints: ["wan:eth1", "client:eth1"]
```

The client must request DHCP itself. The manager injects `kind: linux`,
`image-pull-policy: Never`, `NET_ADMIN`, IPv4 forwarding, and the package build
recipe; do not override those values.

## Lifecycle, security, and diagnosis

Forwarding and masquerade are installed in both modes through the
`ECLAB_WAN_ACCESS_NAT` chain (a POSTROUTING masquerade toward `eth0`) and the
`ECLAB_WAN_ACCESS_FORWARD` chain (forwarding between the lab interface and
`eth0`). DHCP mode also assigns the gateway and runs `dnsmasq` bound to the lab
interface with DNS resolution disabled (`--port=0`). After NAT and, when
enabled, DHCP are configured, the runtime creates
`/run/eclab-wan-access.ready`. The recipe owns no host state, Engulf state,
volumes, or after-destroy cleanup: all rules, addresses, and processes remain
inside the container namespace, destroy removes them, and the local image
remains cached.

During attachment, Containerlab can briefly expose a temporary veth name before
renaming it to the requested endpoint. The runtime retries that disappearing-name
race, but an activation failure on an interface that still exists remains fatal.

The container forwards any traffic received on its lab interface. Apply lab or
host firewall policy and do not use it to bypass an authorization boundary.

For failures, first run `eclab --eclab-containers-help` and confirm
`eclab.containers/wan-access` is active, then inspect `docker logs
clab-<lab>-<node>` and Docker health. Confirm the node has `eth0` plus exactly
one lab interface. In static mode, verify addresses/routes and that no DHCP
variable was set; in DHCP mode, verify the client actually requests a lease.
Finally test `eth0` reachability and inspect `ip address`, the
`ECLAB_WAN_ACCESS_NAT` chain, and the `ECLAB_WAN_ACCESS_FORWARD` chain inside
the container. Redeploy when veth links are missing.
