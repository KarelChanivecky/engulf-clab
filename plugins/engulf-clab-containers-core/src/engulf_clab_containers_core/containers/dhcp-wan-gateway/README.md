# eclab.containers/dhcp-wan-gateway

The DHCP WAN gateway hands out IPv4 leases on a single lab-facing interface
and routes that traffic out through Containerlab management `eth0`, which
carries the node's own default route. It lets a lab client or appliance
obtain an address, gateway, and DNS server by DHCP instead of a fixed
static configuration, while every packet it sends beyond the lab subnet is
masqueraded through `eth0`.

It is not a general WAN, VPN, application proxy, DNS resolver, or SSH
endpoint. It serves DHCP leases on exactly one interface and forwards/NATs
that interface's traffic toward `eth0`.

## Guide

- Interface model
- DHCP environment syntax
- Containerlab example
- Runtime, health, and lifecycle
- Security and troubleshooting

## Interface model

The recipe requires Containerlab management networking and exactly one
lab-facing link:

- `eth0` is management-facing, carries the container's default route, and is
  the interface all lab-subnet traffic is masqueraded through; and
- the single other discovered interface is lab-facing and receives the
  configured gateway address plus the DHCP service.

Connecting zero or more than one lab-facing link makes the container exit
unhealthy; attach exactly one.

## DHCP environment syntax

All variables are optional; unset ones use the defaults below.

| Variable | Meaning | Default |
| --- | --- | --- |
| `ECLAB_DHCP_SUBNET` | IPv4 CIDR subnet assigned to the lab interface | `198.19.0.0/24` |
| `ECLAB_DHCP_GATEWAY` | Gateway address, inside the subnet and outside the pool | `198.19.0.1` |
| `ECLAB_DHCP_POOL_START` / `ECLAB_DHCP_POOL_END` | DHCP pool bounds, inside the subnet | `198.19.0.100` / `198.19.0.200` |
| `ECLAB_DHCP_DNS` | DNS server handed out to clients | `1.1.1.1` |
| `ECLAB_DHCP_LEASE_TIME` | Lease seconds | `43200` |

The gateway and both pool bounds must lie inside the subnet, the gateway
must fall outside the pool range, and pool start must not exceed pool end.
Invalid values make the container exit unhealthy before any DHCP traffic is
served.

## Containerlab example

```yaml
name: dhcp-wan-demo

topology:
  nodes:
    wan:
      image: eclab.containers/dhcp-wan-gateway
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

The client must request DHCP on its attached interface itself; the gateway
does not configure a peer's data-plane interface.

The collection manager injects Linux kind, `image-pull-policy: Never`,
`NET_ADMIN`, and IPv4 forwarding sysctls, plus the package Dockerfile/context.
Do not override those required values.

## Runtime, health, and lifecycle

The entrypoint parses the DHCP configuration once, then waits for exactly
one lab-facing interface to appear. Once found, it assigns the configured
gateway address to that interface, installs `ECLAB_DHCP_SNAT` (POSTROUTING
masquerade toward `eth0`) and `ECLAB_DHCP_FORWARD` (FORWARD accept rules
between the lab interface and `eth0`) chains, and starts `dnsmasq` bound to
that interface with DNS resolution disabled (`--port=0`) so it serves DHCP
only.

After `dnsmasq` starts it creates `/run/eclab-dhcp-wan-gateway.ready`. Docker
health checks that marker every five seconds, with a two-second timeout and
twelve retries. The entrypoint remains attached to the `dnsmasq` process as
PID 1 and exits with its status if it stops.

All rules, addresses, and the `dnsmasq` process are inside the container
network namespace. Destroying the Containerlab node removes them with the
namespace. The recipe owns no host state, Engulf state, volumes, or
after-destroy cleanup. The locally built Docker image remains cached.

## Security and troubleshooting

The gateway grants any client on the lab interface an address and open
forwarding toward `eth0`; it does not authenticate DHCP requests or filter
forwarded traffic beyond the lab/management boundary. Rely on lab/host
firewalls for additional policy, and do not use it to bypass an
authorization boundary.

For diagnosis:

1. Run `eclab --eclab-containers-help` and confirm the core collection is
   active.
2. Inspect `docker logs clab-<lab>-<node>` and Docker health; configuration
   errors are reported before any interface or DHCP setup.
3. Confirm the node has `eth0` plus exactly one lab interface. Use a full
   redeploy when a plain Docker restart has lost Containerlab veth links.
4. Confirm the client actually issues a DHCP request on its attached
   interface; the gateway is passive until one arrives.
5. Inspect `ip address`, and the `ECLAB_DHCP_SNAT` and `ECLAB_DHCP_FORWARD`
   chains, inside the container.
6. Verify `eth0` reachability from the gateway before testing egress from a
   leased client address.
