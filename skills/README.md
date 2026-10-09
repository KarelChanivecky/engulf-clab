# Runtime-generated lab skill

The primary lab-development skill is generated from installed plugin
declarations. Plugins can also contribute complete skills through the path-only
`engulf-clab-skill-api`; `engulf-clab-skill-collector` owns installation and
refresh.

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

Install the collector and whichever skill providers you need in the same
environment as the launcher, then inspect its help:

```bash
python -m pip install engulf-clab-skill-collector engulf-clab-develop-eclab-lab
eclab install-skills "$CODEX_HOME"
```

The argument is the existing configuration root containing or ready to contain
`skills/`, not the skills directory itself. Each plugin contributes an absolute
path to a complete skill directory; the directory basename becomes its target
name. The shared context carries these paths and never embeds the directory
contents. The collector refuses symlinked roots, sources, skills directories,
targets, and targets without a recognized ownership marker. Replacements are
staged beside the target and published atomically.

## Refresh lifecycle

The command preempts normal Containerlab execution after active contributors
have registered their paths. The generated lab-skill provider requests a strict
schema build for explicit installation and a best-effort cached build only when
its target is tracked. The collector stores installed roots and skill names in
user state, then refreshes changed tracked sources during later invocations.
Newly contributed skill names are installed on the next explicit command.
Generated providers can mark their source paths as temporary; the collector
removes those per-invocation trees after each copy or refresh attempt. Installed
targets retain the active runtime and at most one previous recognized backup,
while the schema compiler keeps only the active artifact for each pipeline.
Help, shell completion, and invocations without tracked generated skills do not
request schema work.

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

New plugins that contribute a skill depend on `engulf-clab-skill-api`, package a
complete skill directory, call `record_skill(api, path)` for persistent sources
or `record_temporary_skill(api, path)` for generated sources, and declare the
collector ordering edge so the collector installs after their contribution.
Each contribution is independent, so providers can later split the current lab
skill into separately named skills without adding rendered content to shared
context. Schema-enabled plugins continue to declare `engulf_clab.schema` and
call `record_plugin_schema()` during `before_goal()`.

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
generation lease remain shared. An external edition can render its own skill
directory and contribute its path to the shared collector; target installation
and refresh remain shared across active contributors.

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
A plugin that only serves other plugins passes
`audience=SchemaAudience.SUPPORT`; the compiler keeps it in the fingerprint but
omits it from the catalog, provider YAML, and references so the generated skill
lists only lab-authoring capabilities. Support declarations cannot add topology
controls, task routes, or node kinds.
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
.venv/bin/python -m build --no-isolation plugins/engulf-clab-skill-api
.venv/bin/python -m build --no-isolation plugins/engulf-clab-skill-collector
.venv/bin/python -m build --no-isolation plugins/engulf-clab-develop-eclab-lab
.venv/bin/python -m build --no-isolation skills/engulf-clab-develop-eclab-lab-static
```

For an integration check, install the built packages into a temporary virtual
environment with the wrapper and contributors, run plugin discovery, then run
`install-skills` against a temporary configuration root.
