# Docker image provider API

Install `engulf-docker-image-api` in applications and provider distributions
that exchange Docker image build requests. The package does not parse files,
run Docker, or depend on Containerlab. An application may load JSON, YAML,
environment files, command-line values, or programmatic data and convert it to
an `ImageBuildGraph`.

`ImageRequirement` names an image and carries immutable custom parameters for
that image only. Dependency requirements are complete, independent requests;
parameters are never inherited from another requirement. Providers receive the
complete requirement and return an offer, a rejection, or no response. An
offer declares a `ProvisionAuthority`; the
resolver selects higher authority before provider priority and provider ID. A
terminal rejection blocks equal- or lower-authority offers for a namespace
while still allowing a more explicit provider to override it.

`ImageProvision` supplies either a `DockerfileRecipe` or `DockerPullRecipe` and
optional explicit dependencies. A pull recipe may name a mirror source;
execution pulls that source and retags it as
the required image. `only_if_missing=True` lets execution first accept an
existing local target; it defaults to false so provider mirror recipes continue
to refresh from their selected source. The core package also discovers literal Dockerfile `FROM`
dependencies. Providers are attributed by the dispatcher, not by values
supplied by the provider itself.

Providers should answer from configuration and local metadata without probing a
registry. Set `fallback_on_failure=True` when a failed mirror or cache pull may
fall through to another offer. Use `False` for owned build recipes whose failure
must be surfaced rather than hidden by a public-registry pull.

A mirror plugin only needs to rewrite the source and declare its rank; it does
not check whether the source exists:

```python
from engulf_docker_image_api import (
    DockerPullRecipe,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
)


class LocalMirror:
    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse:
        return ImageProviderResponse.offer(
            ImageProvision(
                requirement.canonical_reference,
                DockerPullRecipe(
                    f"mirror.internal/{requirement.canonical_reference}"
                ),
            ),
            authority=ProvisionAuthority.PREFERRED,
        )
```

If that pull fails, the core excludes this offer and tries the next eligible
provider, eventually reaching its built-in pull of the original reference.

For direct embedding, construct `RegisteredImageProvider` values and pass them
with a graph to `engulf-docker-image-core`. For Engulf-native discovery,
subclass `DockerImagePlugin` and publish it under the Docker-image goal catalog.
`ImageProviderPlugin` wraps a pure provider object when no custom adapter logic
is needed.
Publish that adapter under the goal catalog
`engulf.plugins.v1.goal.v1.org_engulf_docker_image`, using its exact provider
ID as the entry-point name. Engulf attributes every response from the active
endpoint, so providers cannot impersonate one another.
Executable-wrapper adapters can instead register the same provider object in
the invocation-scoped `IMAGE_PROVIDER_CONTEXT` and append graph fragments to
`IMAGE_GRAPH_CONTEXT`.

Provider callbacks must be deterministic and side-effect free. Filesystem and
Docker work belong to the resolver/build phase, after a plan has been selected.
Build parameters are ordinary configuration and must not contain credentials;
use Docker secret facilities for sensitive inputs.
