# Post-deployment instruction API

Install `engulf-clab-instructions-api` alongside `engulf-clab-instructions` and
the contributing plugin. A contributor creates immutable
`DeploymentInstruction` values and records them in an invocation callback:

```python
from engulf_clab_instructions_api import DeploymentInstruction, record_instruction

record_instruction(
    api,
    DeploymentInstruction(
        title="Open the service",
        text="The web service is ready on the host.",
        commands=("docker exec -it clab-demo-web sh",),
        urls=("http://127.0.0.1:8080/",),
    ),
)
```

Commands and URLs are displayed for the operator; the renderer never executes
them. URLs must use `http` or `https` and may not contain embedded credentials.
The `text` field may contain multiple lines. Set `node="web"` to associate an
entry with a topology node.

The API stores an immutable tuple in `INSTRUCTIONS_CONTEXT`. Declare
`INSTRUCTION_CONTEXTS` in both `context_reads` and `context_writes` on a plugin
that calls `record_instruction()`:

```python
from engulf_clab_instructions_api import INSTRUCTION_CONTEXTS

context_reads = INSTRUCTION_CONTEXTS
context_writes = INSTRUCTION_CONTEXTS
```

Add those contexts to existing declarations with set union. Contributions may
be recorded during `before_goal`, `prepare_call`, or `after_call`. They are
invocation-scoped and disappear when the command ends.

If a contributor records entries in `after_goal`, declare the renderer to run
after that callback in the contributor's dependency entry point:

```toml
[project.entry-points."engulf.plugins.v1.dependency.engulf_clab_example"]
"engulf_clab.instructions" = "preprocess=none; postprocess=after"
```

Here `engulf_clab_example` is the declaring plugin ID with dots replaced by
underscores. Plugins that contribute earlier in the invocation need no special
post-goal ordering. Install `engulf-clab-instructions` to render the accumulated
entries after a successful `deploy` or `redeploy`.
