# engulf-clab-health-gates

Waits for Containerlab nodes to become ready after a successful
`eclab deploy`. Install it with
`python -m pip install engulf-clab-health-gates`, or through
`engulf-clab-all-plugins`.

## YAML configuration

Add the top-level extension below. Omitting `nodes` gates every node in
`topology.nodes`; an empty list disables all gates for that topology.

```yaml
name: demo

x-engulf-clab-health-gates:
  timeout: 180  # positive seconds; default 60
  interval: 2   # positive seconds; default 2
  nodes: [router, client]

topology:
  nodes:
    router: {kind: linux}
    client: {kind: linux}
```

| Field | Meaning |
| --- | --- |
| `x-engulf-clab-health-gates.timeout` | Maximum wait for each selected node. |
| `x-engulf-clab-health-gates.interval` | Delay between Docker inspections. |
| `x-engulf-clab-health-gates.nodes` | Optional list of existing topology node names. |

There are no environment variables. Each selected node maps to Containerlab's
standard `clab-<lab-name>-<node-name>` container. The gate succeeds when Docker
reports both `running` and `healthy`. Selected images must define a Docker
`HEALTHCHECK`; a running container without health status does not pass the gate.
The plugin runs only after a successful deploy and reports the final Docker state
on timeout.
