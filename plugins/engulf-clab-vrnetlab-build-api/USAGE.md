# Provider API

Install `engulf-clab-vrnetlab-build-api` when authoring a vrnetlab source
provider. The package defines a shared invocation context containing a node to
source-path map and the builder concurrency limit. It does not select paths,
inspect topology YAML, or build images.

Declare `VRNETLAB_BUILD_CONTEXT` in both `context_reads` and `context_writes`
for a provider that adds sources. The context is invocation scoped and is
discarded after the eclab call. Paths must be absolute so the builder sees the
same location regardless of its working directory.

```python
from engulf_clab_vrnetlab_build_api import (
    VrnetlabBuildAPI,
    VrnetlabBuildContext,
    get_build_context,
)

context = get_build_context(api, create=True)
assert isinstance(context, VrnetlabBuildContext)
build_api = VrnetlabBuildAPI(context)
build_api.set_image_source(Path("/var/tmp/router.qcow2"), "router-1")
pending = build_api.unprovisioned_nodes(("router-1", "router-2"))
# pending == ("router-2",)
build_api.set_image_source(Path("/var/tmp/shared.qcow2"))
# A default source covers router-2 as well.
pending = build_api.unprovisioned_nodes(("router-1", "router-2"))
# pending == ()
# Explicitly replace a source another provider published for router-1.
build_api.set_image_source(
    Path("/var/tmp/generated-router.qcow2"),
    "router-1",
    override=True,
)
build_api.set_build_jobs(2)
```

Construct `VrnetlabBuildAPI` with the invocation's shared
`VrnetlabBuildContext`. Omitting the node name from `set_image_source()` stores
a `default` path. The builder uses an exact node path first and then this
default. A second attempt to set any same key raises `DuplicateImageSourceError`,
even when both paths are equal, unless the caller passes `override=True`. The
flag replaces only the selected node key (including `default` when the name is
omitted); it defaults to `False` so a provider must explicitly choose to
replace another provider's declaration. Providers should use it only when
their source has higher precedence under their documented selection policy.

`build_api.unprovisioned_nodes()` accepts candidate node names and returns a
tuple, preserving their input order. A node is covered by either its exact
source or the `default` source. It reports source declarations only; it does
not inspect Docker or determine whether an image has already been built.
`build_api.uses_default_source(node)` reports whether a node resolves through
the fallback key rather than an exact entry.
Every opted-in node that falls back to the API's `default` source must have the
same `ECLAB_VRNETLAB_TYPE`; publish exact-node sources when different builder
types need different image inputs. The shared builder validates this before
preparing images.

Providers may set the shared build concurrency with
`build_api.set_build_jobs()` after validating their own option syntax. The
builder uses its default when no provider supplies a value. Conflicting
concurrency settings fail clearly.

The source path is a local builder input, usually a qcow2 file or supported
archive. A provider may create or download it during preparation, then publish
its final absolute path. The API does not check file existence, which allows a
provider to prepare the file later in the same invocation.
