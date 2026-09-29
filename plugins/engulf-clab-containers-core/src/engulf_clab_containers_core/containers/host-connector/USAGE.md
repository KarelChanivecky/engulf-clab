# eclab.containers/host-connector

The host connector maps lab-facing virtual IPs to external IPv4 or IPv6 hosts
reachable through Containerlab management `eth0`. It DNATs any IP protocol to
the target and masquerades it through the management network. It is not a DHCP
server, WAN, VPN, application proxy, DNS service, or SSH endpoint.

## Interface and packet flow

- `eth0` is management-facing and must route to every target.
- `lo` holds each VIP as a host address.
- Every other operational interface is lab-facing, excluding Containerlab's
  temporary `clab-*` names; do not use that prefix for a permanent endpoint.

Each VIP is exposed on every lab interface using proxy ARP for IPv4 or proxy
NDP for IPv6. New traffic is translated, its connection is tagged with the
ingress-interface identity, and the unmarked packet is forwarded through
`eth0` and masqueraded. Established and related replies restore that connection
mark onto the reply packet, and one policy table per lab interface sends them
back through the interface that received the request. TCP, UDP, ICMP, and other
IP protocols share the mapping; there are no port-level listeners.

## Mapping syntax

At least one mapping is required:

```text
ECLAB_CONNECT_HOST="<vip>;<external-target>"
ECLAB_CONNECT_HOST_2="<vip>;<external-target>"
```

| Rule | Behavior |
| --- | --- |
| Index zero | The unnumbered key and `_0` are aliases; setting both is an error. |
| Numbering | Decimal indexes may be sparse and are applied numerically. Other suffixes are ignored. |
| Families | A mapping's VIP and target must share a family; separate mappings may use different families. |
| Identity | VIP and target must differ, and each VIP may appear only once. |
| Scope | Every mapping is installed on every current lab-facing interface. |

Whitespace around addresses is ignored. A missing side, extra semicolon,
invalid IP, mixed family, or duplicate VIP is reported before any configuration
is applied and makes the container exit unhealthy.

## Example

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
      kind: linux
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
        ECLAB_CONNECT_HOST_7: "2001:db8:10::50;2001:db8:20::50"
  links:
    - endpoints: ["router:eth1", "external:eth1"]
```

Configure the attached appliance or client to reach each VIP through its lab
interface. The target sees the connector's management address and needs no
route to the lab subnet, but `eth0` must reach it and its firewall must permit
the traffic. The manager injects `kind: linux`, `image-pull-policy: Never`,
`NET_ADMIN`, IP forwarding, disabled reverse path filtering (required by the
policy routing above), and the package build recipe; do not override those
values.

## Lifecycle, security, and diagnosis

The entrypoint parses mappings once at startup, then waits up to **15 seconds**
for at least one lab interface whose operational state is `up` and whose kernel
sysctl paths exist. It ignores Containerlab's temporary `clab-*` veth names so
configuration starts after the endpoint is renamed and brought up. Custom
endpoint names are supported; `eth1` is not required.

If an interface disappears or goes down during configuration, the entrypoint
re-discovers interfaces and retries within the same deadline. A persistent
configuration error on ready interfaces still fails immediately. If no stable
interface can be configured within 15 seconds, it writes
`WARNING: no lab interface became ready within 15s; exiting` to stderr and exits
with status 1. Docker may restart it according to the node's restart policy.

It re-checks the interface set every second, rebuilding its owned
translation, proxy-neighbor, policy-rule, and route state when interfaces
change. Changing a mapping therefore requires a redeploy, not a restart. After
a successful configuration it creates `/run/eclab-host-connector.ready`; Docker
health-checks that marker every five seconds with a two-second timeout and
twelve retries. The marker is removed at process startup, during
reconfiguration, and on exit. If all lab interfaces disappear or go down, the
same 15-second activation deadline applies to recovery. The entrypoint remains
in the interface-watch loop as PID 1 and logs readiness after each successful
configuration. All state stays inside the container namespace;
destroy removes it, while the built image stays cached.

The connector authenticates neither clients nor targets and does not filter by
port. Declare only authorized targets and apply lab or host firewall policy as
needed. Do not use it to bypass an authorization boundary.

For failures, first run `eclab --eclab-containers-help` and confirm
`eclab.containers/host-connector` is active, then inspect `docker logs
clab-<lab>-<node>` and Docker health. Confirm `eth0` plus a lab interface
exist, test the target from the connector through `eth0`, then inspect `ip
address`, `ip neigh`, `ip rule`, the policy route tables, and the `ECLAB_DNAT`,
`ECLAB_SNAT`, `ECLAB_MARK`, and `ECLAB_FORWARD` chains inside the container. If
replies use the wrong link, confirm the ingress interface still exists and that
its interface index and policy table were rebuilt after the topology change.
For IPv6, test management reachability and proxy NDP separately. Redeploy
rather than restarting the container when veth links are missing. For a
15-second timeout, confirm the peer node started and the final lab interface
is up with carrier; an interface stuck under a temporary `clab-*` name is not
ready. Upgrading this package and redeploying rebuilds the helper image with
the startup guard; existing containers and frozen runtime bundles retain their
old entrypoint until replaced or upgraded.
