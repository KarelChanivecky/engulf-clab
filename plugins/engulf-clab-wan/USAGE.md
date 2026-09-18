# engulf-clab-wan

Creates DHCP/NAT WAN bridges for explicitly marked Containerlab bridge nodes.
This is an IPv4 Linux feature. It changes host networking and therefore requires
the necessary Linux and Docker privileges: `sudo`, `ip`, `iptables`, `sysctl`,
and the packaged Python DHCP server. Run the wrapper as your normal user; it
authenticates through sudo before host work and elevates individual commands.
Containerlab's sudo-less setup does not grant plugins these network privileges.
The DHCP child opens its raw socket as root, then drops to the invoking user's
UID/GID before writing PID/lease state and serving packets. A deployment without a marked
bridge does not use this plugin, require root because of it, or change host
networking.

Install with `python -m pip install engulf-clab-wan`, or through
`engulf-clab-all-plugins`. The beta release requires the Engulf 1.0 plugin APIs
used for packaging-declared dependency ordering.

## Configuration

```yaml
topology:
  nodes:
    wan:
      kind: bridge
      labels:
        ECLAB_DHCP_WAN: "true"
        ECLAB_DHCP_SUBNET: "198.19.0.0/24"
    client:
      image: example/client:latest
  links:
    - endpoints: ["client:eth1", "wan:eth1"]
```

| Label | Meaning and default |
| --- | --- |
| `ECLAB_DHCP_WAN` | Required truthy marker. |
| `ECLAB_DHCP_SUBNET` | IPv4 subnet, `198.19.0.0/24`. |
| `ECLAB_DHCP_GATEWAY` | Gateway, `198.19.0.1`. |
| `ECLAB_DHCP_POOL_START` / `ECLAB_DHCP_POOL_END` | Pool bounds, `.100` / `.200`. |
| `ECLAB_DHCP_DNS` | Advertised DNS server, `1.1.1.1`. |
| `ECLAB_DHCP_LEASE_TIME` | Lease seconds, `43200`. |

The connected client must request DHCP itself. The plugin creates the host-side
bridge service, forwarding, and NAT; it does not configure the client's
interface, route, or security policy.

`--eclab-uplink-interface IFACE` selects the host egress interface.
`ECLAB_UPLINK_IF` is its persistent default and the CLI wins. Otherwise the
plugin uses the device returned by `ip route get 1.1.1.1`; select explicitly on
multihomed hosts.

All controls use the fixed `ECLAB` prefix across editions. A known `_DHCP_*`
suffix carrying another edition's prefix (for example `FCLAB_DHCP_WAN`) is
rejected and the expected key is reported. Before Containerlab runs, active
control labels are removed only from the temporary topology; the source retains
them, and Containerlab still receives the ordinary bridge node and its links.

## Validation

Only `kind: bridge` nodes are candidates. The marker may be a mapping key, list
item, or scalar; mapping values `0`, `false`, `no`, and `off` disable it. The
list and scalar forms use all defaults; use a label mapping for non-default
settings. The subnet is normalized, gateway and both pool endpoints must lie
inside it, pool start must not exceed pool end, DNS must be IPv4, and lease
time must be a positive integer. Nothing excludes the gateway from the pool, so
pick pool bounds that skip it. Choose non-overlapping addressing for multiple
bridges; defaults are not made unique automatically.

## Host changes and cleanup

Before deploy or single-source redeploy, the plugin:

- reuses or creates the bridge, assigns the gateway when absent, and brings it
  up;
- records and enables IPv4 forwarding when needed;
- installs comment-owned forwarding and masquerade rules; and
- starts the packaged DHCP process with managed configuration and logs.

Claims are keyed by canonical topology workspace. Another workspace may share
an identically configured bridge; incompatible settings for the same name fail.
Host work is serialized, and an interrupted provisioning journal is rolled back
before the bridge is claimed again.

If a later plugin cannot prepare the deployment, Containerlab never runs and the
plugin releases the bridges that same invocation just claimed, restoring the
workspace to the claims it held beforehand. Bridges an earlier successful deploy
still owns are left in place, so a failed redeploy does not disconnect a running
lab. Releasing those remains the job of `destroy`.

Successful destroy releases the current workspace. On the last release, the
plugin stops only its verified DHCP process, removes only its marked rules and
gateway address, deletes only a bridge it created, and restores the prior IPv4
forwarding value when no managed bridge remains. Pre-existing bridges are
preserved. `destroy -a` or `destroy --all` attempts cleanup for all recorded
WAN workspaces.

Do not manually delete managed state while a WAN lab is active; ownership
records prevent removal of unrelated host resources and support recovery.

## Safety and troubleshooting

- Treat deploy and destroy as privileged host mutations. Parse the topology
  YAML and inspect runtime help before authorizing either operation. Use a
  configured MCP service or the normal local launcher with sudo authorization.
  Detached DHCP startup uses noninteractive sudo after authentication; a denied
  or expired authorization fails normally and preserves recovery metadata.
- For prefix errors, remove stale keys belonging to another edition and use only
  the active prefix shown by that launcher.
- For uplink failures, select an existing egress interface and verify its route
  and NAT policy.
- For DHCP failures, inspect the managed DHCP log through eclab diagnostics,
  verify the bridge/link, and confirm the client requests a lease.
- For cleanup failures, preserve state and inspect the bridge, forwarding
  ownership, PID identity, and marked rules. External changes may require
  deliberate reconciliation before safe cleanup can continue.

## Runtime schema discovery

The plugin records every fixed-prefix WAN label, the uplink variable, and this
packaged `USAGE.md` during `before_goal`. The terminal generator exposes them
only for an active WAN plugin.
