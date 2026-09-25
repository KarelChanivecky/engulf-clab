# Freeze contributor API

Install this package alongside `engulf-clab-freeze`. A contributor publishes one
object in the `engulf_clab.freeze.v1` entry-point group. Its entry-point name must
equal its globally unique `contributor_id`.

Contributors may add only namespaced command flags, sanitize staged files, add
authenticated format-2/3 metadata, resolve recipient bindings during defrost, and
restore state into the unpublished staging directory. Hooks must not alter the
source lab or publish outside the paths supplied in their context.

`FreezeContext.workspace_state`, `FreezeContext.user_state`, and
`DefrostContext.user_state` select the contributor's own Engulf namespace by its
`contributor_id`. They are not the freeze plugin's directory. They may be absent
for direct library callers; receiving a path does not imply the directory exists.

Image-owning plugins may additionally publish a read-only callable under
`engulf_clab.freeze.images.v1`, named with the plugin ID. Its signature is
`image_sources(topology: Path, document: dict, environment: Mapping[str, str])`
and its result is an iterable of immutable `ImageSource` values. The document
contains the staged topology expanded using the original lab's environment;
paths resolve against the original topology. Discovery must not mutate it,
probe registries, build images, or run deploy preparation.

Freeze can also reuse a packaged `ImageProviderPlugin` Dockerfile recipe from
the installed Docker image goal when both its Dockerfile and build context live
inside that provider's installed distribution. This covers static recipes whose
inputs ship with the provider package. Providers that rely on host-local files,
secrets, or runtime-generated recipes must declare those inputs through the
freeze image-source hook. Literal dependencies in Dockerfiles remain available
to recipient image providers or Docker when freeze has no archive source for
them.

`ImageSource` records the image, optional owning node, acquisition kind
(`build`, `archive`, `registry`, or `opaque`), required `ImageInput` files/trees,
recursive image dependencies, and owned node env controls. Build providers must
explicitly establish `rebuildable` and, separately, `offline_rebuildable`;
otherwise freeze captures their output. `identity` records additional non-secret
recipe discriminators used to reject conflicting declarations. `build_only`
allows freeze to remove a recipe-only node when its output is captured.

Each `ImageInput` names a resolved absolute path (or `None` when unavailable),
its selecting env control, and whether it is a standalone binary artifact.
Lean mode may omit standalone artifacts when they are not portable inputs; an
archive source whose file is inside the lab and survives freeze exclusions
remains available at its authored relative path. Missing paths are acquisition
facts, not discovery errors. Archive sources may select an explicit in-archive
reference with `source`; registry sources may specify their remote reference.
Different nodes sharing a tag must declare identical acquisition facts. The
owning package must disable every recipe-enabling control through `controls`
when freeze replaces its output.

`IMAGE_MANIFEST_ENV` is the fixed `ECLAB_IMAGE_ARCHIVE_MANIFEST` node control.
`manifest.read_image_manifest()` validates format 1 image manifests, contained
relative archive paths, and SHA-256 checksums without using Docker. Entries
record `image` and an `action` (`archive`, `build`, `registry`, or `external`).
Archive entries hold `archive` and `sha256`, optionally `source`, `image_id`, and
`platform`. A lean dependency may instead specify `archive_variable`, resolved
from the selecting node's effective env. Other fields record acquisition reasons
and dependencies. Consumers must reject unsupported formats and invalid hashes.

Format 3 runtime providers publish an object in
`engulf_clab.freeze.runtime.v1`, named for the producing edition. Its `edition`
attribute must match the entry-point name. The provider captures tool
identities, checks recipient compatibility, prepares mode-specific artifacts,
and renders a launcher. `runtime_provider(edition)` raises `FreezeError` when
the required edition is absent. Providers must not include credentials or
local paths in archive metadata.
