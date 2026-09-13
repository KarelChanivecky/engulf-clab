# engulf-clab-containers

The `engulf_clab.containers` manager expands package-owned container recipes
into a temporary deploy topology. Install it with one or more collection
packages, then list the active catalog:

```bash
python -m pip install engulf-clab-containers engulf-clab-containers-core
eclab --eclab-containers-help   # listing goes to stdout, so it can be piped
```

## Topology use

Select a recipe by its exact image name; all other fields remain normal
Containerlab YAML:

```yaml
topology:
  nodes:
    connector:
      kind: linux
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
```

Both `<namespace>/<name>` and `<namespace>/<name>:latest` select a managed
recipe. Other tags are unsupported. An unknown image in an active collection's
namespace fails instead of falling through to a registry pull.

Declare the recipe's kind explicitly in the source topology (`kind: linux` for
the maintained recipes). Expansion occurs for deploy and single-source
redeploy; destroy, graph, and direct Containerlab calls use the raw topology. Recipes may reserve `eth0` for
management and treat later interfaces as lab-facing, so follow the selected
recipe's own guide for its interfaces and configuration. The maintained
`eclab.containers` collection currently supplies the `host-connector` and
`wan-access` recipes; the active list is emitted through Engulf diagnostics.

## Injected fields

| Field | Merge behavior |
| --- | --- |
| `image` | Canonicalized to `<namespace>/<name>:latest`. |
| `kind` | Set to the recipe kind; a conflicting value fails. |
| `image-pull-policy` | Required to be `Never` because the image is built locally. |
| `cap-add` | Existing strings remain; missing required capabilities are appended. |
| `sysctls` | Existing values remain unless they conflict with a requirement. |
| `env` | Lab values remain; recipe runtime defaults are added, with conflicts rejected. Build paths are never injected into the topology. |

A recipe that requires management networking accepts the default or explicit
`network-mode: bridge`; incompatible modes fail. The manager registers the
catalog as an image provider and keeps package Dockerfile/context paths out of
the derived topology. Custom build values use the image dispatcher's valid node
`env` conventions such as `ECLAB_IMAGE_PARAM_RELEASE`.

The manager validates the complete active catalog and package assets before
recording mutations. Duplicate names within one collection, duplicate canonical
images, namespace collisions created by underscore-to-hyphen normalization,
missing build assets, and incompatible node fields all fail before resolution.
Each recipe's Dockerfile and context must exist, and the Dockerfile must
live inside its build context. It does not invoke Docker or retain state. The
shared image dispatcher invokes Docker recursively, and the writer removes the
generated topology; built images remain in Docker's cache.

## Troubleshooting

- If the catalog is empty, confirm a collection distribution is installed and
  active in the same launcher or edition.
- Copy image names from `--eclab-containers-help`; only `latest` is managed.
- Resolve field conflicts instead of weakening a recipe requirement, or use a
  normal unmanaged image.
- Missing packaged assets indicate a collection packaging error. Rebuild the
  collection wheel and inspect its contents; running from a source checkout can
  hide package-data omissions. Docker failures belong to the image dispatcher
  and do not imply runtime-field expansion failed.

## Authoring collections

Use `engulf-clab-containers-api` to publish independent typed collections. A
collection owns the namespace derived from its globally unique plugin ID and
must package every build input. Keep recipes generic and push addressing,
credentials, seeds, certificates, routes, and policies into consuming labs.
Collection plugins register immutable recipes during Engulf's before-goal
phase. A recipe may map generic provider parameter names to Docker build
arguments with `parameter_build_args`; the manager reads only parameters on
the requirement for that exact managed image. Managed recipes are
authoritative and disable execution fallback: a failed owned build is reported
instead of silently pulling a same-named public image.

## Runtime schema discovery

At `before_goal`, the manager records its controls and snapshots this packaged
`USAGE.md`, so generated skills describe the installed manager version and the
collections that are actually active.
