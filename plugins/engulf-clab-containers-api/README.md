# engulf-clab-containers-api

This stable contract lets independently published Engulf plugins provide
packaged Containerlab node images. A collection declares immutable build and
node requirements; it does not parse or mutate topology files. The
`engulf_clab.containers` manager is the only topology injector.

Install this package to author or type-check a collection. Lab users normally
receive it through a collection or manager dependency:

```bash
python -m pip install 'engulf-clab-containers-api>=1.0.0,<2'
```

The API imports the stable `engulf_api`, `engulf_executable_wrapper_api`, and
application-neutral `engulf_docker_image_api` contracts. It does not import or
initialize the Engulf runtime.

## Contents

- [Publishing a collection](#publishing-a-collection)
- [Public contract](#public-contract)
- [Manager interaction](#manager-interaction)
- [Packaging checklist](#packaging-checklist)
- [Versioning](#versioning)

## Publishing a collection

Define a normal Engulf plugin with its own globally unique plugin ID:

```python
from pathlib import Path

from engulf_clab_containers_api import (
    ContainerBuildRecipe,
    ContainerCollectionPlugin,
    ContainerDefinition,
    ContainerNodeRequirements,
)

root = Path(__file__).resolve().parent
plugin = ContainerCollectionPlugin(
    "vendor.containers",
    (
        ContainerDefinition(
            name="utility",
            summary="Vendor utility node",
            build=ContainerBuildRecipe(
                dockerfile=root / "containers" / "utility" / "Dockerfile",
                context=root,
                build_args={"EDITION": "community"},
                parameter_build_args={"RELEASE": "APP_RELEASE"},
            ),
            node=ContainerNodeRequirements(cap_add=("NET_ADMIN",)),
        ),
    ),
)
```

Publish that object under both required entry-point groups, using the plugin ID
as the entry-point name:

```toml
[project.entry-points."engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"]
"vendor.containers" = "vendor_collection:plugin"

[project.entry-points."engulf.plugins.v1.application.engulf_clab"]
"vendor.containers" = "vendor_collection:plugin"

[project.entry-points."engulf.plugins.v1.dependency.vendor_containers"]
"engulf_clab.containers" = "preprocess=after; postprocess=none"
```

The dependency group name is the plugin ID with dots replaced by underscores.
It is the only supported place to declare the manager ordering edge.

The collection package depends on `engulf-clab-containers-api>=1.0.0,<2` and
`engulf-clab-containers>=0.1.0,<1`. Its plugin ID owns the image namespace after
underscores are converted to hyphens, so the example exposes
`vendor.containers/utility:latest`. Two active plugins cannot own the same
namespace. Dockerfiles and everything they `COPY` must be included in the
collection wheel and inside the declared build context.

The declarative node contract intentionally supports only typed Containerlab
fields: `kind`, `cap_add`, `sysctls`, `environment`, and whether management
networking is required. Container-specific runtime configuration belongs in
the topology node's `env` mapping.

## Public contract

All public values are immutable dataclasses or immutable registrations:

| Type / function | Fields and behavior |
| --- | --- |
| `ContainerBuildRecipe` | Absolute `dockerfile` and `context`; optional fixed `build_args`; optional `parameter_build_args` mapping provider parameter names to Docker build-argument names. The manager later validates the package assets. |
| `ContainerNodeRequirements` | `kind="linux"`; unique `cap_add` tuple; string/int `sysctls`; string/int default `environment`; `requires_management=True`. Boolean mapping values are rejected even though `bool` subclasses `int`. |
| `ContainerDefinition` | Lowercase Docker-safe `name`, nonempty `summary`, build recipe, and optional node requirements. Names may contain internal `.`, `_`, or `-`. |
| `RegisteredContainerCollection` | Validated dot-qualified `plugin_id` plus a tuple of definitions. Usually created internally by the collection plugin. |
| `ContainerCollectionPlugin` | Declarative `ExecutableWrapperPlugin` that publishes its recipes to call context before the manager runs. |
| `ContainerImageProvider` | Application-neutral provider over registered collections; resolves exact `latest` names and maps declared custom parameters to Docker build arguments. |
| `image_namespace(plugin_id)` | Replaces underscores with hyphens; the namespace plus definition name yields `<namespace>/<name>:latest`. |

Mappings are copied into read-only proxies and tuples may not contain duplicate
capabilities. A collection's plugin ID must be lowercase and dot-qualified.
Construction fails early for malformed declarations so invalid package data
cannot reach topology preparation.

An application using the generic Docker-image goal can wrap
`ContainerImageProvider` with `ImageProviderPlugin` and publish it under
`engulf.plugins.v1.goal.v1.org_engulf_docker_image`. This does not require the
application to parse Containerlab YAML or run the eclab executable-wrapper goal.

## Manager interaction

The collection plugin appends a `RegisteredContainerCollection` to context
`engulf_clab.containers.collections` during Engulf's before-goal phase. The
ordering edge that makes the manager run after collection registration is
declared by each collection distribution, not by this package: add
`engulf_clab.containers` to the collection's
`engulf.plugins.v1.dependency.<plugin_id>` entry-point group. Engulf 0.2 rejects
`plugin_dependencies` declared in code, so `ContainerCollectionPlugin` carries no
default edge for subclasses to inherit. The manager then:

1. verifies namespaces, unique names, and package assets;
2. lists the active catalog for `--eclab-containers-help`;
3. matches only an explicit topology image using the canonical name or the same
   name without `:latest`;
4. merges required Containerlab runtime fields through the shared topology editor;
5. registers the catalog as a neutral Docker image provider; and
6. lets the image dispatcher recursively resolve and build the selected recipe
   before the writer materializes the temporary topology.

A consuming topology supplies custom build values through the image dispatcher's
ordinary node `env` conventions. If a suffix appears in `parameter_build_args`,
the provider adds the mapped Docker build argument. Parameters belong only to
the requirement for that exact image and are not inherited by dependencies.

Only `latest` is supported for managed recipes. A different tag under an active
collection namespace is rejected instead of falling through to an unrelated
registry image. Two active plugin IDs whose underscore-normalized namespaces
collide are also rejected.

## Packaging checklist

- Include the Dockerfile and every `COPY`/`ADD` input in the built wheel.
- Use absolute paths derived from `__file__`; never assume a source checkout or
  current working directory.
- Set the context narrowly enough to avoid packaging secrets or unrelated files.
- Keep lab-specific IP addresses, routes, users, credentials, certificates,
  seeds, and policies in the consuming topology or bind mounts.
- Depend on the compatible API and manager release lines.
- Publish the same plugin object under both eclab entry-point groups.
- Declare the manager ordering edge in the distribution's
  `engulf.plugins.v1.dependency.<plugin_id>` entry-point group:

  ```toml
  [project.entry-points."engulf.plugins.v1.dependency.my_vendor_containers"]
  "engulf_clab.containers" = "preprocess=after; postprocess=none"
  ```
- Install the built wheel into a clean environment and confirm the recipe is
  visible through the selected launcher's container-catalog help.

## Versioning

The `1.x` API is the compatibility boundary for independently published
collections. Adding an optional field with a safe default may be compatible;
renaming fields, changing accepted value types, altering image namespace rules,
or changing manager lifecycle expectations requires a major-version review.
Collection packages should use `>=1.0.0,<2`, not an unbounded dependency. The
`1.0` floor is the beta baseline that requires packaging-declared plugin
dependencies and the Engulf 1.0 plugin APIs.
