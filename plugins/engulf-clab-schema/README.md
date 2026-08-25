# engulf-clab runtime schema

This plugin composes the topology schema supplied by the selected Containerlab
source with declarations recorded by active Engulf plugins. The fixed registry
context contains named schema pipelines: base contributors default to `eclab`,
and a superset edition may declare one parent and contribute to its own child
pipeline. It produces:

- `catalog.md`, the compact task-first discovery surface for an agent;
- `catalog.json`, the same task and provider routing in a queryable form;
- `plugins/<plugin-id>/schema.yaml`, one compact agent-facing capability schema
  per active plugin;
- `plugins/containerlab.node_kinds/schema.yaml`, the node-kind index harvested
  from the selected Containerlab and vrnetlab repositories;
- `plugins/containerlab.node_kinds/node-kinds/<kind>/schema.yaml`, one compact
  source record per exact Containerlab kind, plus whichever upstream documents
  exist for that kind;
- `manifest.json`, the complete provider inventory and ownership index;
- `clab.schema.json`, the exact composed topology validation schema; and
- `plugins/<plugin-id>/...`, the packaged detailed references named by routes.

The manifest and catalog identify the requested pipeline, its root-first
lineage, and the declaration pipeline for every provider. Provider YAML repeats
that provenance, and the composed topology schema records the pipeline ID and
lineage in extension fields.

The catalog directs an agent to relevant plugin YAML files and then to detailed
references. The agent does not need to open the much larger validation schema
for capability discovery. Base Containerlab CLI syntax is intentionally not
frozen into plugin declarations: the catalog names the selected launcher's
`--help` as the runtime authority.
Each canonical wrapper flag also names its `environment_default` when one
exists, so agents know which supported environment variable persists the
setting and that the CLI form overrides it for one invocation.

The composed validation schema remains self-contained. A shared Containerlab
definition is cloned at most once for each plugin-owned mutation location and
then reused, so repeated controls do not create historical definition chains.

For a source checkout, `schemas/clab.schema.json` in that checkout is always the
first choice. If it is unavailable, the plugin reads the same Git commit and may
fetch only that exact repository revision. For a binary, it uses
`containerlab version --json`. `--eclab-containerlab-schema FILE` supplies a
local schema for private or offline binary builds. `CONTAINERLAB_SCHEMA` is the
supported persistent environment default, and the CLI option wins.

Node kinds come from the selected Containerlab schema. The generator maps them
to `docs/manual/kinds/` in that same checkout or exact fetched commit and, where
a unique mapping exists, to the vendor/product README in the selected vrnetlab
source. Missing documents are represented as missing and do not remove a valid
kind. Ambiguous vrnetlab matches are not guessed.

vrnetlab source precedence is a published resolved hint, a prepared checkout,
`VRNETLAB_DIR`, the managed user-state checkout, then
`VRNETLAB_REPO`/`VRNETLAB_VERSION` or the configured default repository. A
custom Containerlab repository without an explicit revision uses and records
its resolved `HEAD`; it does not inherit the default fork's branch. Explicit
skill generation refreshes moving repository selections and records exact
commits. Normal refresh reuses the verified cache until another lifecycle
source update or strict generation occurs.

The ensure-containerlab and ensure-vrnetlab plugins own source precedence. They
publish non-mutating selections before the terminal generator and resolved
sources after preparation. Direct environment and state inference here is only
a compatibility fallback when an owning ensure plugin is absent.

Build requests select exactly one pipeline and that ID must match the running
executable's normalized short product name. The generator resolves only that
pipeline's parent chain, rejects missing parents, cycles, conflicting
declarations, or duplicate provider IDs, and compiles all inherited and local
raw declarations in one pass. Failures in unrelated pipelines are ignored.
Inherited `{short_product}` placeholders expand against the current application
metadata when contributions are recorded.

Normal calls refresh lazily after executable preparation and never fail solely
because documentation generation failed. When no generated skill is tracked,
they do not request schema work at all. Otherwise the generator first compares a
persisted input fingerprint covering the application, active plugin
distributions and declarations, packaged-reference hashes, compiler format, and
the selected Containerlab/vrnetlab sources. A matching complete artifact is
reused without resolving repositories, harvesting node kinds, or compiling the
full schema. Local checkout fingerprints include the exact Git revision and
cheap stamps for the schema and relevant upstream documentation.

Explicit consumers request a strict build and receive a nonzero result when an
exact current bundle cannot be made. Missing or incomplete cached artifacts are
regenerated. Artifacts are fingerprinted under
`pipelines/<pipeline-id>/artifacts/<fingerprint>/`, with a separate
`pipelines/<pipeline-id>/latest.json` cache record. Legacy unscoped `artifacts/`
and `latest.json` values are ignored and rebuilt. Source caches and the global
schema-generation lease remain shared across pipelines. Repository URLs are
sanitized before entering manifests or diagnostics.
