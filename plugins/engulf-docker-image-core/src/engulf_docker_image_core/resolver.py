from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from engulf_docker_image_api import (
    DockerfileRecipe,
    ImageBuildGraph,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    RegisteredImageProvider,
    canonical_image_reference,
    ordered_providers,
)

from .dockerfile import dockerfile_requirements
from .errors import ImageResolutionError


@dataclass(frozen=True, slots=True)
class AttributedImageResponse:
    provider_id: str
    response: ImageProviderResponse


@dataclass(frozen=True, slots=True)
class ProvisionAttempt:
    provider_id: str
    provision: ImageProvision


ProviderLookup = Callable[[ImageRequirement], Sequence[AttributedImageResponse]]


@dataclass(frozen=True, slots=True)
class ResolvedImage:
    image: str
    requirement: ImageRequirement
    provision: ImageProvision | None
    provider_id: str | None
    dependencies: tuple[str, ...]
    attempt: ProvisionAttempt | None = None
    authority: ProvisionAuthority = ProvisionAuthority.DEFAULT
    fallback_on_failure: bool = False

    @property
    def external(self) -> bool:
        return self.provision is None


@dataclass(frozen=True, slots=True)
class ResolvedImageGraph:
    roots: tuple[str, ...]
    images: tuple[ResolvedImage, ...]

    def image(self, reference: str) -> ResolvedImage:
        canonical = canonical_image_reference(reference)
        for item in self.images:
            if item.image == canonical:
                return item
        raise KeyError(reference)


def merge_image_graphs(graphs: Sequence[ImageBuildGraph]) -> ImageBuildGraph:
    if any(not isinstance(graph, ImageBuildGraph) for graph in graphs):
        raise TypeError("graphs must contain ImageBuildGraph values")
    return ImageBuildGraph(
        tuple(root for graph in graphs for root in graph.roots),
        tuple(provision for graph in graphs for provision in graph.provisions),
    )


def registered_provider_lookup(
    providers: Sequence[RegisteredImageProvider],
) -> ProviderLookup:
    ordered = ordered_providers(providers)

    def lookup(requirement: ImageRequirement) -> tuple[AttributedImageResponse, ...]:
        responses: list[AttributedImageResponse] = []
        for registered in ordered:
            try:
                response = registered.provider.provide(requirement)
            except Exception as error:
                raise ImageResolutionError(
                    f"provider {registered.provider_id} failed while considering "
                    f"{requirement.reference}: {error}"
                ) from error
            if response is not None:
                if not isinstance(response, ImageProviderResponse):
                    raise ImageResolutionError(
                        f"provider {registered.provider_id} returned an invalid response"
                    )
                responses.append(AttributedImageResponse(registered.provider_id, response))
        return tuple(responses)

    return lookup


def resolve_image_graph(
    graph: ImageBuildGraph,
    providers: Sequence[RegisteredImageProvider] = (),
    *,
    provider_lookup: ProviderLookup | None = None,
    excluded_attempts: frozenset[ProvisionAttempt] = frozenset(),
) -> ResolvedImageGraph:
    if not isinstance(graph, ImageBuildGraph):
        raise TypeError("graph must be an ImageBuildGraph")
    if type(excluded_attempts) is not frozenset or any(
        not isinstance(item, ProvisionAttempt) for item in excluded_attempts
    ):
        raise TypeError("excluded_attempts must contain ProvisionAttempt values")
    lookup = provider_lookup or registered_provider_lookup(providers)
    seeds = _seed_provisions(graph.provisions)
    nodes: dict[str, ResolvedImage] = {}
    request_cache: dict[ImageRequirement, str] = {}
    active: list[str] = []

    def resolve(requirement: ImageRequirement) -> str:
        cached = request_cache.get(requirement)
        if cached is not None:
            return cached
        requested = requirement.canonical_reference
        if requested in active:
            cycle = " -> ".join((*active[active.index(requested) :], requested))
            raise ImageResolutionError(f"Docker image dependency cycle: {cycle}")
        active.append(requested)
        try:
            seed = seeds.get(requested)
            if seed is not None:
                attempt = ProvisionAttempt("graph", seed)
                if attempt not in excluded_attempts:
                    selected = _resolve_candidate(
                        requirement,
                        seed,
                        "graph",
                        resolve,
                        nodes,
                        attempt=attempt,
                        authority=ProvisionAuthority.EXPLICIT,
                        fallback_on_failure=False,
                    )
                    request_cache[requirement] = selected
                    return selected

            responses = tuple(lookup(requirement))
            indexed_offers = tuple(
                (index, item)
                for index, item in enumerate(responses)
                if item.response.provision is not None
            )
            terminal_authority = max(
                (
                    item.response.authority
                    for item in responses
                    if item.response.rejection is not None and item.response.terminal
                ),
                default=None,
            )
            offers = tuple(
                item
                for _, item in sorted(
                    indexed_offers,
                    key=lambda value: (-int(value[1].response.authority), value[0]),
                )
                if terminal_authority is None or item.response.authority > terminal_authority
            )
            rejections = tuple(
                f"{item.provider_id}: {item.response.rejection}"
                for item in responses
                if item.response.rejection is not None
            )
            failures: list[str] = []
            excluded: list[str] = []
            for attributed in offers:
                provider_id = attributed.provider_id
                response = attributed.response
                provision = response.provision
                assert provision is not None
                attempt = ProvisionAttempt(provider_id, provision)
                if attempt in excluded_attempts:
                    excluded.append(f"{provider_id}: prior provisioning attempt failed")
                    continue
                nodes_before = dict(nodes)
                cache_before = dict(request_cache)
                try:
                    selected = _resolve_candidate(
                        requirement,
                        provision,
                        provider_id,
                        resolve,
                        nodes,
                        attempt=attempt,
                        authority=response.authority,
                        fallback_on_failure=response.fallback_on_failure,
                    )
                except ImageResolutionError as error:
                    nodes.clear()
                    nodes.update(nodes_before)
                    request_cache.clear()
                    request_cache.update(cache_before)
                    failures.append(f"{provider_id}: {error}")
                    continue
                request_cache[requirement] = selected
                return selected
            if indexed_offers or rejections:
                details = (*failures, *excluded, *rejections)
                raise ImageResolutionError(
                    f"cannot provide Docker image {requirement.reference}: " + "; ".join(details)
                )
            external = nodes.get(requested)
            if external is None:
                nodes[requested] = ResolvedImage(requested, requirement, None, None, ())
            elif not external.external:
                request_cache[requirement] = external.image
                return external.image
            request_cache[requirement] = requested
            return requested
        finally:
            active.pop()

    roots = tuple(resolve(root) for root in graph.roots)
    return ResolvedImageGraph(
        tuple(dict.fromkeys(roots)),
        tuple(nodes[key] for key in sorted(nodes)),
    )


def _resolve_candidate(
    requirement: ImageRequirement,
    provision: ImageProvision,
    provider_id: str,
    resolve: Callable[[ImageRequirement], str],
    nodes: dict[str, ResolvedImage],
    *,
    attempt: ProvisionAttempt,
    authority: ProvisionAuthority,
    fallback_on_failure: bool,
) -> str:
    requested = requirement.canonical_reference
    supplied = provision.canonical_image
    if requested != supplied:
        raise ImageResolutionError(
            f"offered tag {provision.image} does not satisfy requested tag {requirement.reference}"
        )
    dependencies = _combined_dependencies(provision)
    resolved_dependencies = tuple(resolve(dependency) for dependency in dependencies)
    resolved_dependencies = tuple(dict.fromkeys(resolved_dependencies))
    candidate = ResolvedImage(
        supplied,
        requirement,
        provision,
        provider_id,
        resolved_dependencies,
        attempt,
        authority,
        fallback_on_failure,
    )
    previous = nodes.get(supplied)
    if previous is not None and not previous.external:
        if _resolved_definition(previous) != _resolved_definition(candidate):
            raise ImageResolutionError(f"conflicting build recipes for Docker image {supplied}")
        return previous.image
    nodes[supplied] = candidate
    return supplied


def _seed_provisions(provisions: tuple[ImageProvision, ...]) -> dict[str, ImageProvision]:
    result: dict[str, ImageProvision] = {}
    for provision in provisions:
        key = provision.canonical_image
        previous = result.get(key)
        if previous is not None and _provision_definition(previous) != _provision_definition(
            provision
        ):
            raise ImageResolutionError(f"conflicting graph provisions for Docker image {key}")
        result[key] = previous or provision
    return result


def _combined_dependencies(provision: ImageProvision) -> tuple[ImageRequirement, ...]:
    # Only Dockerfile builds can declare static FROM bases worth resolving; vrnetlab
    # (make-driven) and pull recipes contribute no discoverable image dependencies.
    discovered = (
        dockerfile_requirements(provision.recipe)
        if isinstance(provision.recipe, DockerfileRecipe)
        else ()
    )
    values = (*provision.dependencies, *discovered)
    result: list[ImageRequirement] = []
    seen: set[ImageRequirement] = set()
    for requirement in values:
        if requirement not in seen:
            seen.add(requirement)
            result.append(requirement)
    return tuple(result)


def _provision_definition(provision: ImageProvision) -> tuple[object, ...]:
    return (
        provision.canonical_image,
        provision.recipe,
        provision.dependencies,
    )


def _resolved_definition(image: ResolvedImage) -> tuple[object, ...]:
    assert image.provision is not None
    return (_provision_definition(image.provision), image.dependencies)
