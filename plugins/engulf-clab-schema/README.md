# engulf-clab runtime schema

This plugin composes the topology schema supplied by the selected Containerlab
source with declarations recorded by active Engulf plugins. It produces:

- `catalog.md`, the compact task-first discovery surface for an agent;
- `catalog.json`, the same task and provider routing in a queryable form;
- `plugins/<plugin-id>/schema.yaml`, one compact agent-facing capability schema
  per active plugin;
- `manifest.json`, the complete provider inventory and ownership index;
- `clab.schema.json`, the exact composed topology validation schema; and
- `plugins/<plugin-id>/...`, the packaged detailed references named by routes.

The catalog directs an agent to relevant plugin YAML files and then to detailed
references. The agent does not need to open the much larger validation schema
for capability discovery. Base Containerlab CLI syntax is intentionally not
frozen into plugin declarations: the catalog names the selected launcher's
`--help` as the runtime authority.

The composed validation schema remains self-contained. A shared Containerlab
definition is cloned at most once for each plugin-owned mutation location and
then reused, so repeated controls do not create historical definition chains.

For a source checkout, `schemas/clab.schema.json` in that checkout is always the
first choice. If it is unavailable, the plugin reads the same Git commit and may
fetch only that exact repository revision. For a binary, it uses
`containerlab version --json`. `CONTAINERLAB_SCHEMA` supplies a local schema for
private or offline binary builds.

Normal calls refresh lazily after executable preparation and never fail solely
because documentation generation failed. Explicit consumers request a strict
build and receive a nonzero result when an exact current bundle cannot be made.
Artifacts are fingerprinted and cached in plugin user state. Repository URLs are
sanitized before entering manifests or diagnostics.
