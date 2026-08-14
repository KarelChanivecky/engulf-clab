# engulf-clab-containers-api

This stable contract lets independently published Engulf plugins provide
packaged Containerlab node images. A collection declares immutable build and
node requirements; it does not parse or mutate topology files. The
`engulf_clab.containers` manager is the only topology injector.

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
```

The collection package depends on `engulf-clab-containers-api>=1.0,<2` and
`engulf-clab-containers>=0.1,<0.2`. Its plugin ID owns the image namespace after
underscores are converted to hyphens, so the example exposes
`vendor.containers/utility:latest`. Two active plugins cannot own the same
namespace. Dockerfiles and everything they `COPY` must be included in the
collection wheel and inside the declared build context.

The declarative node contract intentionally supports only typed Containerlab
fields: `kind`, `cap_add`, `sysctls`, `environment`, and whether management
networking is required. Container-specific runtime configuration belongs in
the topology node's `env` mapping.
