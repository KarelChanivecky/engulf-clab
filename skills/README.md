# Runtime-generated lab skill

The primary lab-development skill is no longer maintained as a repository snapshot.
Installed Engulf plugins describe their own commands, CLI controls, runtime
variables, topology extensions, use cases, exclusions, and packaged references
through `engulf-clab-schema-api`.

`engulf-clab-schema` runs after schema contributors. The fixed schema-registry
context contains partitioned declaration pipelines. It resolves only the
pipeline requested by the running executable, inherits its single parent chain,
and combines those declarations with the exact Containerlab schema selected for
the invocation:

1. the checkout selected by `--eclab-containerlab-dir` or the
   `CONTAINERLAB_DIR` environment default;
2. the schema at the selected checkout's Git revision;
3. the repository and revision reported by the selected Containerlab binary;
4. `--eclab-containerlab-schema` or the `CONTAINERLAB_SCHEMA` environment
   default for an exact private or offline binary build.

The result is fingerprinted from the exact Containerlab and vrnetlab source
identities, application metadata, active plugin distributions and versions,
declarations, and reference contents. It is therefore an inventory of the
installed runtime, not of this checkout.

Each runtime contains a task catalog, one compact YAML capability schema per
plugin, and a complete self-contained Containerlab schema for machine
validation. Agents route through the catalog and read only relevant plugin YAML
files; they do not use the full validation schema for feature discovery.
The catalog also routes specialized `kind:` values through a generated upstream
provider containing one small record per kind and the available documentation
from the selected Containerlab and vrnetlab repositories.
The installer also appends the current catalog to `SKILL.md`, after durable
runtime-selection, topology-design, safety, and diagnostic guidance.

## Install

Install `engulf-clab-develop-eclab-lab` in the same environment as the base
wrapper, then inspect eclab help. Its command and target are static:

```bash
eclab install-develop-eclab-lab-skill "$CODEX_HOME"
```

The argument is the configuration root containing `skills/`, not the skills
directory itself. The command creates
`$CODEX_HOME/skills/develop-eclab-lab/`. This collector is inactive under every
other executable, so it cannot generate or refresh the eclab target there.

The installer refuses a symlinked configuration root, a symlinked skills
directory, and an existing target without its generated-skill ownership marker.
Recognized prior generations are moved to a backup directory beside the active
skill. Schema fingerprints remain under `references/runtimes/` so an existing
conversation can keep using the snapshot it started with.

## Refresh lifecycle

Explicit installation requests a strict schema compile and preempts normal
Containerlab execution. Thereafter the plugin tracks the installation in user
state. Help, shell completion, and invocations with no tracked target request no
schema work.
Other wrapper lifecycle points compare a persisted fingerprint of the active
plugin declarations, package versions, compiler format, and selected local or
repository sources. They compile only after an input change or missing cache
artifact, and refresh only stale or incomplete tracked targets. A deleted
target or one that no longer has its ownership marker is untracked; an unsafe or
manually replaced target is reported and left alone.

## Static comparison baseline

The historical self-contained skill remains buildable as
`engulf-clab-develop-eclab-lab-static` for effectiveness comparisons. It keeps
the last static snapshot from before runtime-generated composition and installs
beside the generated target as `develop-eclab-lab-static`:

```bash
python -m pip install engulf-clab-develop-eclab-lab-static
develop-eclab-lab-static-install
```

Invoke `$develop-eclab-lab-static` explicitly when evaluating the baseline and
`$develop-eclab-lab` for the generated version. The static package is frozen as
a comparison artifact; normal plugin and documentation changes update only the
generated skill pipeline.

Newly discovered eclab plugins participate automatically when they depend on
`engulf_clab.schema` and call `record_plugin_schema()` during `before_goal`.
Because the generator is declared as an after-dependency, it sees every
contribution before compiling.

## Superset edition contract

The public schema API keeps the physical Engulf context IDs stable while its
typed `SchemaRegistry` partitions declarations by pipeline. Existing plugins
write to `eclab` by default. A superset edition registers, for example,
`SchemaPipeline("example-edition", "eclab")`; its own plugins construct
`PluginSchema(..., pipeline_id="example-edition")`. Its collector issues a
`SchemaBuildRequest(..., pipeline_id="example-edition")` only when that
executable is running and later retrieves
`compiled_schema(api, pipeline_id="example-edition")`.

The requested pipeline must equal the normalized executable short product. The
generator resolves the root-first chain and compiles parent and child raw
declarations once. Every parent contribution is inherited; duplicate provider
IDs are not overrides. Missing parents, cycles, conflicting declarations, and
multiple pipelines requested in one invocation fail. Unrelated declaration
failures are ignored, and inherited `{short_product}` placeholders resolve from
the running edition metadata.

Each pipeline has its own `pipelines/<pipeline-id>/latest.json` and artifact
tree in schema-generator user state. Containerlab/vrnetlab source caches and the
generation lease remain shared. The API exposes the final compiled bundle to an
external edition; the external edition owns its distinct skill template,
installation command, target, and refresh tracking.

## Contributor contract

Create one mutable import-time builder per plugin:

```python
PLUGIN_SCHEMA = PluginSchema("example.plugin", package="example_plugin")
```

Declare commands and controls with `add_command()`, `add_cli_argument()`,
`add_cli_flag()`, `add_runtime_var()`, `add_root_prop()`, `add_node_prop()`,
`add_link_prop()`, and `add_node_var()`. Attach command/lifecycle scope,
relationships, path bases, privilege, host tools, ownership, and safe examples
with `annotate()`. Declare plugin-level requirements and ordering with
`require_host_tool()`, `require_privilege()`, and `order()`. Add task routing
with `route()`, concise applicability guidance with `use_case()` and `reject()`,
and detailed installed-package usage material with repeatable `refer()` calls.
Reference `USAGE.md`, not contributor-only `CONTRIBUTING.md` or `AGENTS.md`, so
the generated skill contains operational guidance without implementation noise.
Every explanation must be one line and at most 240 characters.

The API signatures and validation rules are documented in
`plugins/engulf-clab-schema-api/README.md`. Contributors must declare the schema
ordering edge in their distribution's
`engulf.plugins.v1.dependency.<plugin_id>` entry-point group, include
`SCHEMA_CONTEXTS` in their context contract, derive their executable-wrapper
adapter from `SchemaBackedPlugin`, and call
`record_plugin_schema(api, PLUGIN_SCHEMA)` from `before_goal`. Engulf rejects
`plugin_dependencies` declared in code, and the current schema API omits the
`SCHEMA_PLUGIN_DEPENDENCY` constant that used to express this edge.

## Validation

```bash
make check-skill
.venv/bin/python -m build --no-isolation plugins/engulf-clab-schema-api
.venv/bin/python -m build --no-isolation plugins/engulf-clab-schema
.venv/bin/python -m build --no-isolation plugins/engulf-clab-develop-eclab-lab
.venv/bin/python -m build --no-isolation skills/engulf-clab-develop-eclab-lab-static
```

For an integration check, install the built packages into a temporary virtual
environment with the wrapper and contributors, run plugin discovery, then run
the static eclab install command against a temporary configuration root.
