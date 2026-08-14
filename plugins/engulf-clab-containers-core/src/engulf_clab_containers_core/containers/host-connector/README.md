# eclab.containers/host-connector

The host connector maps lab-facing virtual IP addresses to external IPv4 or
IPv6 hosts reachable through Containerlab management `eth0`. It lets an
appliance or client send any IP protocol to a stable lab-side VIP while the
connector DNATs the packet to a real target and source-NATs it through the
management network.

It is not a general WAN, DHCP server, VPN, application proxy, DNS service, or
SSH endpoint. It performs deterministic address translation and per-interface
reply steering only.

## Guide

- Interface and packet-flow model
- Mapping environment syntax
- Containerlab example
- Runtime, health, and lifecycle
- Security and troubleshooting

## Interface and packet-flow model

The recipe requires Containerlab management networking:

- `eth0` is management-facing and must route to every external target;
- `lo` holds each VIP as a host address; and
- every other discovered interface is lab-facing.

Each configured VIP is exposed on every lab-facing interface. For IPv4 the
connector enables proxy ARP; for IPv6 it enables proxy NDP. New traffic arriving
for a VIP is translated to its target, marked with the ingress-interface
identity, forwarded through `eth0`, and masqueraded. Connection marks restore
established/related replies, and one policy table per lab interface sends them
back through the same interface that received the request.

The translation is protocol-independent: TCP, UDP, ICMP, and other IP protocols
follow the same mapping. There is no port-level mapping or listener inside the
connector.

## Mapping environment syntax

At least one mapping is required:

```text
ECLAB_CONNECT_HOST="<vip>;<external-target>"
ECLAB_CONNECT_HOST_2="<vip>;<external-target>"
```

| Rule | Behavior |
| --- | --- |
| Unnumbered key | Alias for index `0`. |
| `ECLAB_CONNECT_HOST_0` | Equivalent to the unnumbered key; setting both is an error. |
| Numbered keys | Decimal indexes may be sparse and are applied in numeric order. Non-decimal suffixes are ignored. |
| Address families | VIP and target within one mapping must both be IPv4 or both IPv6. Different mappings may use different families. |
| Identity | VIP and target must differ, and each VIP may appear only once. |
| Scope | Every mapping is installed on every current lab-facing interface. |

Whitespace around the two addresses is ignored. Missing sides, extra
semicolons, non-IP values, mixed families, and duplicate VIPs make the container
exit unhealthy.

## Containerlab example

```yaml
name: connector-demo

topology:
  nodes:
    router:
      kind: linux
      image: example/router:latest
      exec:
        - ip addr add 10.10.10.1/24 dev eth1
        - ip link set eth1 up
    external:
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
        ECLAB_CONNECT_HOST_7: "2001:db8:10::50;2001:db8:20::50"
  links:
    - endpoints: ["router:eth1", "external:eth1"]
```

Configure the router/client to reach the VIP through its attached interface.
The target sees the connection as originating from the connector's management
address because of masquerading. The target does not need a return route to the
lab subnet, but it must be reachable from `eth0` and permit the translated
traffic.

The collection manager injects Linux kind, `image-pull-policy: Never`,
`NET_ADMIN`, IPv4/IPv6 forwarding sysctls, reverse-path-filter controls, and the
package Dockerfile/context. Do not override those required values.

## Runtime, health, and lifecycle

The entrypoint parses mappings once, then checks the interface set every second.
It waits until at least one lab-facing interface exists. Whenever that set
changes, it rebuilds the connector-owned IPv4/IPv6 chains, proxy-neighbor
entries, policy rules, and routes for the current interfaces.

After a successful configuration it creates
`/run/eclab-host-connector.ready`. Docker health checks that marker every five
seconds, with a two-second timeout and twelve retries. The entrypoint remains in
the interface-watch loop as PID 1 and logs one readiness line.

All rules and addresses are inside the container network namespace. Destroying
the Containerlab node removes them with the namespace. The recipe owns no host
state, Engulf state, volumes, or after-destroy cleanup. The locally built Docker
image remains cached.

## Security and troubleshooting

The connector grants lab nodes network reachability to each declared target and
does not authenticate or filter by port. Declare only targets the lab is allowed
to access, and rely on lab/host firewalls for additional policy. Do not use it to
bypass an authorization boundary. The target logs the connector management
address rather than the original lab address.

For diagnosis:

1. Run `eclab --eclab-containers-help` and confirm the core collection is active.
2. Inspect `docker logs clab-<lab>-external` and Docker health; syntax errors are
   reported before configuration.
3. Confirm the node has `eth0` plus at least one lab interface. Use a full
   redeploy when a plain Docker restart has lost Containerlab veth links.
4. Test target reachability from the connector through `eth0` before testing the
   VIP path.
5. Inspect `ip address`, `ip neigh`, `ip rule`, policy route tables, and the
   `ECLAB_DNAT`, `ECLAB_SNAT`, `ECLAB_MARK`, and `ECLAB_FORWARD` chains inside
   the container.
6. For IPv6, verify management IPv6 reachability and proxy-NDP behavior on the
   lab segment separately from IPv4.
7. If replies use the wrong link, confirm the ingress interface still exists and
   its interface index/policy table was rebuilt after topology changes.
