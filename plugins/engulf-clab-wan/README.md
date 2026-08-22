# engulf-clab-wan

Creates DHCP/NAT WAN bridges for marked Containerlab bridge
nodes. Install it with `python -m pip install engulf-clab-wan`, or through
`engulf-clab-all-plugins`. It changes host networking and therefore requires the
necessary Linux/Docker privileges.

This is an IPv4 Linux feature. The launcher needs root plus `ip`, `iptables`,
`sysctl`, and the packaged Python DHCP server. No external `dnsmasq` service is
required. Deployments without a marked bridge do not require root or change host
networking.

## Contents

- [YAML configuration](#yaml-configuration)
- [Lifecycle and cleanup](#lifecycle-and-cleanup)
- [Validation and prefix rules](#validation-and-prefix-rules)
- [Provisioned host resources](#provisioned-host-resources)
- [Safety and troubleshooting](#safety-and-troubleshooting)

## YAML configuration

Mark a bridge node with `ECLAB_DHCP_WAN`. The plugin removes its own control
labels from the generated topology before Containerlab receives it.

```yaml
topology:
  nodes:
    wan:
      kind: bridge
      labels:
        ECLAB_DHCP_WAN: "true"
        ECLAB_DHCP_SUBNET: "198.19.0.0/24"
        ECLAB_DHCP_GATEWAY: "198.19.0.1"
        ECLAB_DHCP_POOL_START: "198.19.0.100"
        ECLAB_DHCP_POOL_END: "198.19.0.200"
        ECLAB_DHCP_DNS: "1.1.1.1"
        ECLAB_DHCP_LEASE_TIME: "43200"
    client:
      image: example/client:latest
  links:
    - endpoints: ["client:eth1", "wan:eth1"]
```

The connected client/appliance interface must request DHCP itself. The plugin
creates the bridge-side service and route/NAT plumbing; it does not configure a
node's data-plane interface, default route, or security policy.

| Label | Meaning |
| --- | --- |
| `ECLAB_DHCP_WAN` | Required marker. Any truthy value enables the managed WAN. |
| `ECLAB_DHCP_SUBNET` | IPv4 subnet; default `198.19.0.0/24`. |
| `ECLAB_DHCP_GATEWAY` | Gateway address; default `198.19.0.1`. |
| `ECLAB_DHCP_POOL_START` / `ECLAB_DHCP_POOL_END` | DHCP pool bounds; defaults `.100` and `.200`. |
| `ECLAB_DHCP_DNS` | DHCP DNS server; default `1.1.1.1`. |
| `ECLAB_DHCP_LEASE_TIME` | DHCP lease seconds; default `43200`. |

| Invocation environment | Meaning |
| --- | --- |
| `ECLAB_UPLINK_IF` | Optional host uplink interface, bypassing automatic detection. |

`ECLAB` is a fixed label prefix, the same across every edition. It does not
vary with the active application's product name, so labels written for one
edition work unchanged under any other. A label ending in a known `_DHCP_*`
suffix but using any other prefix (for example `FCLAB_DHCP_WAN`) is rejected
with the expected `ECLAB_*` key rather than treated as an alias.

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

## Validation and prefix rules

Only nodes with `kind: bridge` are candidates. The marker may be a mapping key,
list item, or scalar label; mapping values `0`, `false`, `no`, and `off` disable
it. Configuration values come from a label mapping or the documented defaults.

The subnet is parsed with host bits normalized. Gateway and both pool endpoints
must be inside it, pool start must not exceed pool end, DNS must be an IPv4
address, and lease time must be a positive integer. Validate separate managed
bridges for non-overlapping addressing; the plugin does not invent per-bridge
defaults.

Every control suffix uses the fixed `ECLAB` prefix. If a label token ends in a
known `_DHCP_*` suffix but uses another prefix, analysis fails and names the
expected `ECLAB_*` key. This prevents a stray label copied from older or
unrelated documentation from being silently ignored.

Before Containerlab runs, the plugin removes only its active control labels from
the temporary topology. The source retains them and Containerlab still receives
the ordinary bridge node and links.

## Provisioned host resources

For each bridge the plugin:

1. reuses an existing Linux bridge or creates one;
2. adds the configured gateway/prefix when absent and sets the interface up;
3. records and enables `net.ipv4.ip_forward` when required;
4. installs comment-owned forward/return and NAT masquerade rules;
5. starts a detached packaged DHCP server with user-state config, PID, lease,
   and log files; and
6. records the workspace claim and completed configuration.

The uplink comes from `ECLAB_UPLINK_IF` or the `dev` returned by
`ip route get 1.1.1.1`. Set it explicitly on multihomed hosts where that probe
does not select the intended egress.

One user-scoped registry coordinates every workspace. A second workspace may
share an identically configured bridge; incompatible configuration for the same
name fails. Per-bridge leases and an IPv4-forwarding lease serialize host work.
A provisioning journal allows the next call to recognize and roll back an
interrupted setup before claiming the bridge again.

On the last successful release, cleanup stops only the PID whose command line
matches the managed DHCP configuration, removes only rules carrying the plugin's
bridge comment, removes only the gateway address it added, and deletes only a
bridge it created. It restores the original IPv4-forwarding value when no
managed bridges remain. A pre-existing bridge is preserved.

## Safety and troubleshooting

- Treat deploy/destroy as privileged mutations. Parse YAML and inspect runtime
  help before authorizing either operation.
- If root is required, use the configured MCP service or an explicitly
  privileged local launcher; do not grant a general shell to an untrusted agent.
- For prefix errors, remove stale keys from another edition and use only the
  active prefix shown by that launcher.
- For uplink failures, set `ECLAB_UPLINK_IF` to an existing egress interface
  and verify its route/NAT policy.
- For DHCP failures, inspect the managed DHCP log through eclab diagnostics and
  verify the bridge is up, the client link uses the expected interface, and the
  client actually requests DHCP.
- For cleanup failures, preserve the registry/journal and inspect bridge,
  forwarding, PID identity, and comment-owned rules. Do not delete shared state
  while another workspace claims the bridge.
- If an outside tool changes a managed address/rule/process, reconcile that host
  state deliberately; ownership checks may refuse destructive cleanup.

## Runtime schema discovery

The plugin records every fixed-prefix WAN label, the uplink variable, and this
packaged README during `before_goal`. The terminal generator exposes them only
for an active WAN plugin.
