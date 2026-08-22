# Runtime-generated lab skill

The lab-development skill is no longer maintained as a repository snapshot.
Installed Engulf plugins describe their own commands, CLI controls, runtime
variables, topology extensions, use cases, exclusions, and packaged references
through `engulf-clab-schema-api`.

`engulf-clab-schema` runs after schema contributors. It combines those
declarations with the exact Containerlab schema selected for the invocation:

1. `CONTAINERLAB_DIR/schemas/clab.schema.json` or another selected checkout;
2. the schema at the selected checkout's Git revision;
3. the repository and revision reported by the selected Containerlab binary;
4. `CONTAINERLAB_SCHEMA` for an exact private or offline binary build.

The result is fingerprinted from the Containerlab source identity, application
metadata, active plugin distributions and versions, declarations, and reference
contents. It is therefore an inventory of the installed runtime, not of this
checkout.

Each runtime contains a task catalog, one compact YAML capability schema per
plugin, and a complete self-contained Containerlab schema for machine
validation. Agents route through the catalog and read only relevant plugin YAML
files; they do not use the full validation schema for feature discovery.
The installer also appends the current catalog to `SKILL.md`, after durable
runtime-selection, topology-design, safety, and diagnostic guidance.

## Install

Install `engulf-clab-develop-lab-skill` in the same environment as the wrapper,
then inspect the edition's help. The command is derived from its short product
name. For the standard edition:

```bash
eclab install-develop-eclab-lab-skill "$CODEX_HOME"
```

The argument is the configuration root containing `skills/`, not the skills
directory itself. The command creates
`$CODEX_HOME/skills/develop-eclab-lab/`. Other editions receive corresponding
command and skill names.

The installer refuses a symlinked configuration root, a symlinked skills
directory, and an existing target without its generated-skill ownership marker.
Recognized prior generations are moved to a backup directory beside the active
skill. Schema fingerprints remain under `references/runtimes/` so an existing
conversation can keep using the snapshot it started with.

## Refresh lifecycle

Explicit installation requests a strict schema compile and preempts normal
Containerlab execution. Thereafter the plugin tracks the installation in user
state. Normal wrapper lifecycle points compile the active runtime schema and
refresh tracked targets when the fingerprint changes. A deleted target is
untracked; an unsafe or manually replaced target is reported and left alone.

Newly discovered plugins participate automatically when they depend on
`engulf_clab.schema` and call `record_plugin_schema()` during `before_goal`.
Because the generator is declared as an after-dependency, it sees every
contribution before compiling.

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
and detailed installed-package material with repeatable `refer()` calls. Every
explanation must be one line and at most 240 characters.

The API signatures and validation rules are documented in
`plugins/engulf-clab-schema-api/README.md`. Contributors must declare
`SCHEMA_PLUGIN_DEPENDENCY`, include `SCHEMA_CONTEXTS` in their context contract,
and call `record_plugin_schema(api, PLUGIN_SCHEMA)` from `before_goal`.

## Validation

```bash
make check-skill
.venv/bin/python -m build --no-isolation plugins/engulf-clab-schema-api
.venv/bin/python -m build --no-isolation plugins/engulf-clab-schema
.venv/bin/python -m build --no-isolation plugins/engulf-clab-develop-lab-skill
```

For an integration check, install the built packages into a temporary virtual
environment with the wrapper and contributors, run plugin discovery, then run
the edition-aware install command against a temporary configuration root.
