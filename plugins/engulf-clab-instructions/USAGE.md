# Post-deployment instructions

Install `engulf-clab-instructions` in the same Python environment as `eclab`.
Engulf discovers the package automatically; installing it activates the
renderer. The separate `engulf-clab-instructions-api` package lets other plugins
add commands, web pages, and notes to the same output. The plugin dependencies
supply the topology parser and writer; it needs no additional host tools or
privileges.

After a successful `eclab deploy` or single-topology `eclab redeploy`, the
renderer prints configured instructions through the plugin logger. Failed
deployments do not show them. The renderer does not make network requests or
execute contributed commands.

## Configuration

The active eclab environment key is `ECLAB_INSTRUCTIONS`. A process-wide value
can be supplied in the shell:

```sh
ECLAB_INSTRUCTIONS='Check the service logs after deployment.' eclab deploy -t lab.clab.yml
```

Topology environment declarations can set a default or a more specific value.
Containerlab YAML remains the base topology language; see the upstream
[topology schema](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
The following examples show the plugin convention layered onto valid Containerlab
`env` fields:

```yaml
topology:
  defaults:
    env:
      ECLAB_INSTRUCTIONS: "Check the service at http://127.0.0.1:8080."
  nodes:
    web:
      kind: linux
      env:
        ECLAB_INSTRUCTIONS: "For this node, run: docker exec -it clab-lab-web sh"
```

`topology.defaults.env` applies to nodes that inherit the default. A node, group,
or kind declaration supplies scoped text for the affected nodes. An explicit
topology value takes precedence over the process-wide variable for that node;
the shell value is used for nodes with no topology declaration. Defaults are
shown once, while scoped values include the node name. With no selected topology,
the process-wide value is shown when available.

The renderer removes `ECLAB_INSTRUCTIONS` declarations from the generated deploy
topology so this wrapper control is not passed into nodes. The source topology is
not edited. Values may use the shared parser's environment expansion, including
the adjacent `<topology>.env` file, when the topology references that value:

```yaml
topology:
  defaults:
    env:
      ECLAB_INSTRUCTIONS: "${POST_DEPLOY_NOTE}"
```

Containerlab's native `env-files` setting is for node environment and is not a
source for this wrapper control.

The key uses the active application's short product name as its prefix. For the
`eclab` application that exact key is `ECLAB_INSTRUCTIONS`.

## Plugin contributions

Install `engulf-clab-instructions-api` with a contributing plugin. That plugin
can publish structured follow-up items from an invocation callback:

```python
from engulf_clab_instructions_api import DeploymentInstruction, record_instruction

record_instruction(
    api,
    DeploymentInstruction(
        title="Open the web UI",
        text="The dashboard is exposed on the host.",
        commands=("docker exec -it clab-lab-web sh",),
        urls=("http://127.0.0.1:8080/",),
    ),
)
```

Each entry has a title and at least one of free-form text, a tuple of commands,
or a tuple of URLs. Set `node="web"` to label a node-specific entry. Commands
are displayed only. URLs must be absolute HTTP(S) URLs without credentials.
Multiline text is supported; terminal control characters are rejected.

Contributors declare `INSTRUCTION_CONTEXTS` in both `context_reads` and
`context_writes`. Contributions made before `after_goal()` need no additional
ordering. If a contributor records from `after_goal()`, it declares the renderer
to run afterward in its packaging metadata:

```toml
[project.entry-points."engulf.plugins.v1.dependency.engulf_clab_example"]
"engulf_clab.instructions" = "preprocess=none; postprocess=after"
```

`engulf_clab_example` is the contributor's plugin ID with dots replaced by
underscores. See the API package's `USAGE.md` for its complete public contract.

## State, cleanup, and security

The plugin stores no persistent state and takes no resource leases. Its plan and
plugin contributions live only for the current invocation. The topology
declaration is removed from the writer's derived deployment file and remains in
the source YAML for later deployments. There is no additional cleanup command.

Configured text is displayed to the terminal through Engulf's callback logger.
Avoid putting secrets in it. Contributed commands are never launched, and URLs
are never fetched. A terminal may interpret formatting in ordinary text only if
it is emitted with a control sequence, so terminal control characters are
rejected by the API.

## Troubleshooting

- If no message appears, check that the deploy exited with status zero and that
  the variable is spelled `ECLAB_INSTRUCTIONS`.
- Check precedence: a topology declaration takes precedence over the process
  environment for nodes that inherit it.
- Per-node topology text requires a selected source topology. `redeploy --name`
  can still use the process-wide environment value.
- If another plugin contributes after-goal entries, declare its packaging order
  before `engulf_clab.instructions` so those entries are visible to the renderer.
