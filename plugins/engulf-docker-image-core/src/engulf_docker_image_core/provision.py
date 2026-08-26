from __future__ import annotations

from collections.abc import Sequence

from engulf_api import InvocationAPI
from engulf_docker_image_api import (
    DockerPullRecipe,
    ImageBuildGraph,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    RegisteredImageProvider,
)

from .build import DEFAULT_IMAGE_BUILD_JOBS, ImageBuildOutcome, build_resolved_graph
from .errors import ImageBuildError, ImageResolutionError
from .resolver import (
    AttributedImageResponse,
    ProviderLookup,
    ProvisionAttempt,
    registered_provider_lookup,
    resolve_image_graph,
)

DEFAULT_PULL_PROVIDER_ID = "org.engulf.docker.pull"


def provision_image_graph(
    graph: ImageBuildGraph,
    *,
    api: InvocationAPI,
    providers: Sequence[RegisteredImageProvider] = (),
    provider_lookup: ProviderLookup | None = None,
    max_workers: int = DEFAULT_IMAGE_BUILD_JOBS,
) -> ImageBuildOutcome:
    """Resolve and provision every image, retrying lower-ranked offers after failures."""
    base_lookup = provider_lookup or registered_provider_lookup(providers)
    response_cache: dict[ImageRequirement, tuple[AttributedImageResponse, ...]] = {}
    excluded: set[ProvisionAttempt] = set()
    failures: list[str] = []

    def lookup(requirement: ImageRequirement) -> tuple[AttributedImageResponse, ...]:
        cached = response_cache.get(requirement)
        if cached is not None:
            return cached
        responses = tuple(base_lookup(requirement))
        fallback = AttributedImageResponse(
            DEFAULT_PULL_PROVIDER_ID,
            ImageProviderResponse.offer(
                ImageProvision(
                    requirement.canonical_reference,
                    DockerPullRecipe(requirement.canonical_reference),
                    origin="default Docker registry pull",
                ),
                authority=ProvisionAuthority.FALLBACK,
            ),
        )
        result = (*responses, fallback)
        response_cache[requirement] = result
        return result

    while True:
        try:
            resolved = resolve_image_graph(
                graph,
                provider_lookup=lookup,
                excluded_attempts=frozenset(excluded),
            )
        except ImageResolutionError as error:
            if not failures:
                raise
            raise ImageBuildError(
                "all Docker image provisioning candidates failed: "
                + "; ".join((*failures, str(error)))
            ) from error
        try:
            return build_resolved_graph(resolved, api=api, max_workers=max_workers)
        except ImageBuildError as error:
            if not error.failures:
                raise
            nonfallback = tuple(
                failure for failure in error.failures if not failure.fallback_on_failure
            )
            if nonfallback:
                raise
            attempts = {
                ProvisionAttempt(failure.provider_id, failure.provision)
                for failure in error.failures
            }
            new_attempts = attempts - excluded
            if not new_attempts:
                raise
            excluded.update(new_attempts)
            failures.extend(
                f"{failure.provider_id} failed for {failure.image}: {failure.reason}"
                for failure in error.failures
            )
            api.logger.warning(
                "retrying Docker image provisioning after candidate failure: %s",
                "; ".join(failures[-len(error.failures) :]),
            )
