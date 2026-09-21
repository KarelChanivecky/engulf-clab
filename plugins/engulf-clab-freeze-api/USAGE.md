# Freeze contributor API

Install this package alongside `engulf-clab-freeze`. A contributor publishes one
object in the `engulf_clab.freeze.v1` entry-point group. Its entry-point name must
equal its globally unique `contributor_id`.

Contributors may add only namespaced command flags, sanitize staged files, add
authenticated format-2 metadata, resolve recipient bindings during defrost, and
restore state into the unpublished staging directory. Hooks must not alter the
source lab or publish outside the paths supplied in their context.

Image-owning plugins may additionally publish a read-only callable under
`engulf_clab.freeze.images.v1`, named with the plugin ID. Its signature is
`image_sources(topology: Path, document: dict, environment: Mapping[str, str])`
and its result is an iterable of immutable `ImageSource` values. The document
contains the staged topology expanded using the original lab's environment;
paths resolve against the original topology. Discovery must not mutate it,
probe registries, build images, or run deploy preparation.

`ImageSource` records the image, optional owning node, acquisition kind
(`build`, `archive`, `registry`, or `opaque`), required `ImageInput` files/trees,
recursive image dependencies, and owned node env controls. Build providers must
explicitly establish `rebuildable` and, separately, `offline_rebuildable`;
otherwise freeze captures their output. `identity` records additional non-secret
recipe discriminators used to reject conflicting declarations. `build_only`
allows freeze to remove a recipe-only node when its output is captured.

Each `ImageInput` names a resolved absolute path (or `None` when unavailable),
its selecting env control, and whether it is a binary artifact that lean mode
omits. Missing paths are acquisition facts, not discovery errors. Archive
sources may select an explicit in-archive reference with `source`; registry
sources may specify their remote reference. Different nodes sharing a tag must
declare identical acquisition facts. The owning package must disable every
recipe-enabling control through `controls` when freeze replaces its output.

`IMAGE_MANIFEST_ENV` is the fixed `ECLAB_IMAGE_ARCHIVE_MANIFEST` node control.
`manifest.read_image_manifest()` validates format 1 image manifests, contained
relative archive paths, and SHA-256 checksums without using Docker. Entries
record `image` and an `action` (`archive`, `build`, `registry`, or `external`).
Archive entries hold `archive` and `sha256`, optionally `source`, `image_id`, and
`platform`. A lean dependency may instead specify `archive_variable`, resolved
from the selecting node's effective env. Other fields record acquisition reasons
and dependencies. Consumers must reject unsupported formats and invalid hashes.
