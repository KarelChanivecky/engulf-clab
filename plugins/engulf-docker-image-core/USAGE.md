# Docker image resolver and builder

`engulf-docker-image-core` accepts the neutral graph from
`engulf-docker-image-api`; it has no Containerlab, YAML, or eclab dependency.

Use `resolve_image_graph(graph, providers)` to create a deterministic plan.
Offers are ordered by provision authority, then provider priority and ID. If an
offered recipe needs another image, the resolver repeats the same process.
Candidate failures backtrack to later offers. A terminal rejection blocks
equal- or lower-authority offers, while a higher-authority offer may override
it. Cycles, conflicting recipes, and unresolved terminal rejections fail the
plan.

Use `provision_image_graph` for end-to-end execution. It adds a low-authority
`docker pull` offer for every otherwise unclaimed requirement, executes the
selected graph, and retries resolution without a failed offer when that offer
allows fallback. This supports a preferred local-mirror pull followed by the
ordinary image reference without registry probes during provider discovery.
The built-in ordinary-reference fallback inspects the exact local tag while
executing: an existing image satisfies the requirement, while a missing image
is pulled. Preferred provider recipes keep their declared execution behavior.
Provider responses are cached across execution retries.

Dockerfile analysis follows literal `FROM` instructions and external
`COPY --from=<image>` sources, ignores prior-stage
aliases and `scratch`, and expands global `ARG` values when known. A dynamic base
expression that cannot be resolved fails provisioning; provide its global build
argument so the complete graph is known before execution. Explicit provision
dependencies are combined with discovered bases and copy sources. Global
Dockerfile `ARG` defaults and recipe build arguments are expanded; stage aliases
are excluded and unresolved dynamic image sources fail before Docker runs.

An archive recipe is executed with `docker load`, then retagged when the archive
does not already carry the target reference. A recipe that names no source
requires the archive to carry the target or exactly one image; a multi-image
archive fails with its loaded count rather than retagging an arbitrary member.
Loads acquire the target tag's lease and the selected source's lease, and
`only_if_missing=True` accepts an existing local target instead of reloading.
Outcomes report loads in `loaded`, separately from `built`, `pulled`, and
`reused`.

`build_resolved_graph` executes every selected build, load, or pull recipe on
every invocation. Dependencies finish before their consumers, independent branches
may run in parallel, and leases cover every output tag and mirror pull source.
Docker's layer cache remains the freshness policy for builds; the built-in
missing-only pull fallback may reuse an existing exact local tag. Outcomes
report that case in `reused`, separately from `pulled`. No images are removed
afterward. Dockerfile recipes may not enable `--pull`; their base images must be
supplied through the graph.

`DockerImageGoal(loader)` is the smallest Engulf-native application strategy:
the injected loader may parse any source format into a graph, and providers are
dispatched through `DockerImagePlugin` hooks. Wrapper applications may call the
same resolver and scheduler from their own goal adapter with a registry of
`RegisteredImageProvider` values.

For example, a loader for a JSON, `.env`, or custom values file only needs to
return `ImageBuildGraph((ImageRequirement(reference),))`; it does not need to
know which provider owns the reference. Construct the application's Engulf goal
with `DockerImageGoal(loader)`. Installed provider adapters published under
`engulf.plugins.v1.goal.v1.org_engulf_docker_image` are then called for every
root and recursively discovered base. The application retains Engulf's normal
activation policy: explicitly include provider IDs with a declared/allowlist
policy, or deliberately select the compatible goal catalog with a blocklist
policy.

A minimal JSON-driven application can be this small (input parsing stays owned
by the application):

```python
import json
from pathlib import Path

from engulf import ApplicationDefinition, PluginPolicy
from engulf_api import Invocation
from engulf_docker_image_api import ImageBuildGraph, ImageRequirement
from engulf_docker_image_core import DockerImageGoal


def load(invocation: Invocation) -> ImageBuildGraph:
    path = Path(invocation.arguments[0])
    if not path.is_absolute():
        path = invocation.cwd / path
    document = json.loads(path.read_text(encoding="utf-8"))
    return ImageBuildGraph(tuple(ImageRequirement(reference) for reference in document["images"]))


application = ApplicationDefinition(
    application_id="org.example.image-builder",
    display_name="image-builder",
    goal_factory=lambda: DockerImageGoal(load),
    vendor="Example",
    product="Image Builder",
    short_product_name="image-builder",
    version="1.0.0",
    plugin_policy=PluginPolicy.allow_all_except(()),
).create()

try:
    raise SystemExit(application.run())
finally:
    application.close()
```

The same loader could read YAML, a variable-value file, or construct the graph
entirely in code without changing any provider.
