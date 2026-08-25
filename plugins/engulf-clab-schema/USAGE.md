# engulf-clab runtime schema

Install with `python -m pip install engulf-clab-schema`.

The plugin composes the schema from the selected Containerlab source with
declarations from active Engulf plugins. A generated skill should use each
artifact for its specific purpose:

| Artifact | Use |
| --- | --- |
| `catalog.md` / `catalog.json` | Route a task to relevant providers. |
| `plugins/<plugin-id>/schema.yaml` | Inspect concise controls, relationships, safety, and reference routes. |
| `plugins/containerlab.node_kinds/schema.yaml` | Index every exact Containerlab kind. |
| `plugins/containerlab.node_kinds/node-kinds/<kind>/schema.yaml` | One compact source record per kind, plus whichever upstream documents exist for it. |
| `manifest.json` | Inspect provider ownership, source identity, pipeline, and lineage. |
| `clab.schema.json` | Validate the final topology; do not use it for feature discovery. |

Each canonical wrapper flag also names its `environment_default` when one
exists, so an agent knows which supported environment variable persists the
setting and that the CLI form overrides it for a single invocation.

Detailed usage references live beneath their provider. Base Containerlab CLI
syntax remains runtime-specific; use the selected launcher's `--help`.

## Source identity

For a checkout, the generator first uses its working-tree
`schemas/clab.schema.json`, then that file from the checkout's exact commit,
and finally may fetch the file from the origin at that exact revision. The last
step can access the repository; an unrelated latest schema is never
substituted. For a binary, the generator uses `containerlab version --json` to
resolve its reported repository and revision. A custom Containerlab repository
given without an explicit revision uses and records its resolved `HEAD`; it
does not inherit the default fork's branch. `--eclab-containerlab-schema FILE`
supplies an exact local schema for private or offline builds;
`CONTAINERLAB_SCHEMA` is its persistent default and the CLI option wins.

The ensure-containerlab and ensure-vrnetlab plugins own source precedence. They
publish non-mutating selections before the terminal generator and resolved
sources after preparation. Direct environment and state inference here is only
a compatibility fallback for when an owning ensure plugin is absent.

Node kinds and any available Containerlab/vrnetlab documentation come from the
same selected sources. The generator maps kinds to `docs/manual/kinds/` in that
same checkout or exact fetched commit and, where a unique mapping exists, to
the vendor/product README in the selected vrnetlab source. Missing
documentation does not remove a valid kind, and ambiguous vrnetlab matches are
not guessed.

vrnetlab source precedence is a published resolved hint, a prepared checkout,
`VRNETLAB_DIR`, the managed user-state checkout, then `VRNETLAB_REPO` /
`VRNETLAB_VERSION` or the configured default repository.

Source provenance is recorded in the manifest. The composed topology schema
also records the requested pipeline ID and its root-first lineage in the
`x-eclab-schema-pipeline` and `x-eclab-schema-lineage` extension fields, and
provider YAML and the catalog repeat that provenance.

## Editions and freshness

Each request compiles one pipeline matching the running executable. A superset
pipeline inherits its declared parent and adds its own providers; unrelated
pipelines are not compiled. Base contributors default to the `eclab` pipeline,
and a superset edition may declare one parent and contribute to its own child
pipeline. Artifacts are fingerprinted under
`pipelines/<pipeline-id>/artifacts/<fingerprint>/`, with a separate
`pipelines/<pipeline-id>/latest.json` cache record, allowing edition skills to
coexist.

Normal tracked-skill refresh is lazy, best effort, and happens after executable
preparation. When no generated skill is tracked, no schema work is requested at
all. A complete matching fingerprint is reused without resolving repositories,
harvesting node kinds, or compiling the full schema; changed application
metadata, active plugin distributions, plugin declarations, reference contents,
compiler format, or selected sources produces a new runtime. Local checkout
fingerprints include the exact Git revision plus cheap stamps for the schema
and relevant upstream documentation. Normal refresh reuses a verified moving
repository selection until an ensure-plugin source update or strict generation
resolves it again. Explicit installation refreshes moving references, requests
a strict current build, records exact commits, and returns a nonzero result
rather than presenting stale output as current. Repository credentials and
absolute reference-source paths are not exposed in generated artifacts.
