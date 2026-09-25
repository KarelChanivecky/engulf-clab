# Fortinet operation guard

Install `engulf-clab-fortinet-operation-guard` beside `engulf-clab`. The
package is discovered automatically through its Engulf plugin entry points; it
has no additional command, flag, environment variable, topology field, lease,
or persistent state.

## Behavior

When the selected Containerlab topology contains an effective node with either
`kind: fortinet_fortigate` or `kind: fortinet_fortiproxy`, the plugin rejects:

- `eclab deploy --reconfigure` (including `-c`);
- `eclab restart`; and
- `eclab deploy` when the selected lab is already running.

The diagnostic is:

```text
Fortinet devices currently do not support <operation>.
```

For a plain deploy, the plugin reads Docker's Containerlab labels during call
preparation. It matches `clab-topo-file` against the selected source or the
stable derived topology path, then falls back to the Containerlab lab name when
the topology label is unavailable. A stopped lab may be deployed normally.

Containerlab YAML remains the base topology language. The node-kind behavior is
an eclab convention layered on valid Containerlab fields; see the upstream
[`schemas/clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json)
for the base syntax.

## Lifecycle, security, and cleanup

The explicit reconfigure and restart checks happen before wrapper preparation.
The running-state check is a read-only `docker container ls` and `docker
container inspect` sequence during preparation. The plugin does not start,
stop, restart, reconfigure, or remove containers and does not write topology or
Engulf state. It requires the caller's existing Docker read access; if Docker
state cannot be inspected, the deploy fails closed rather than risk an
unsupported operation.

Uninstalling the package removes the guard and does not change any lab,
container, image, or state. Use a supported full deploy or destroy/recreate
workflow for Fortinet labs.

## Troubleshooting

- If the guard does not activate, verify that the package is installed in the
  same environment as `eclab` and check `eclab --engulf-plugin-list`.
- If a Fortinet kind is inherited from `topology.defaults`, `topology.kinds`, or
  `topology.groups`, the effective declaration is still checked.
- If a normal deploy reports a Docker inspection failure, restore Docker access
  and retry; do not bypass the check by treating the lab as stopped.
