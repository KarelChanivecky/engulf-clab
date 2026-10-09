# Host port check

Install `engulf-clab-port-check` in the same Python environment as eclab. The
package is discovered automatically when installed.

On `eclab deploy` with a local topology, the plugin checks each node's
Containerlab `ports` list. A port is checked only against the requested
protocol: omitted suffix means TCP, while `/udp` means UDP. For example:

```yaml
topology:
  nodes:
    web:
      kind: linux
      ports:
        - "8080:80"
        - "5353:53/udp"
```

When an occupied port is found, an interactive terminal asks for another host
port from 1 through 65535 and repeats until the answer is valid and open. The
chosen host port is applied to the temporary deploy topology; the source YAML
is not edited. Once deployment succeeds, the plugin logs the replacement at
the end and records the lab's node/protocol/port assignments in workspace
state. A later conflict names that lab only when Docker confirms it is running.
Otherwise the message reports the occupying process when the operating system
exposes its PID and command line.

Use `--eclab-not-interactive` to fail with the conflict message instead of
prompting, or `--eclab-auto-port` to choose an available port automatically.
Both flags are consumed by eclab and are not passed to Containerlab. Automatic
selections are reported when deployment finishes, including its exit status.

The live socket probe is authoritative for whether a port is currently
available. Saved ownership is informational and is never used to claim that a
port is occupied. The probe and bind are separate operations, so another
process can claim a port before Containerlab does. Only numeric
`host:container[/tcp|udp]` declarations are checked. Process details may be
unavailable when the OS hides them, and an open port can become occupied after
the probe. No sockets remain open after checking.

If Containerlab reports a bind failure after the check, inspect host listeners
and verify that the node's `ports` value uses a static numeric host port. The
upstream [Containerlab topology schema](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json)
defines the base topology syntax.
