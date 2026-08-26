from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from engulf_api import (
    GoalPhase,
    GoalRequirement,
    InvocationAPI,
    Plugin,
    PluginOrder,
    validate_global_identifier,
)

DOCKER_IMAGE_GOAL_REQUIREMENT = GoalRequirement("org.engulf.docker-image", 1)
IMAGE_PROVIDER_CONTEXT = "org.engulf.docker-image.providers"
IMAGE_GRAPH_CONTEXT = "org.engulf.docker-image.graphs"


def _nonempty(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    if "\0" in value:
        raise ValueError(f"{label} must not contain NUL characters")
    return value


def _image_reference(value: object, *, label: str = "image reference") -> str:
    result = _nonempty(value, label=label)
    if any(character.isspace() for character in result):
        raise ValueError(f"{label} must not contain whitespace")
    return result


def canonical_image_reference(reference: str) -> str:
    """Return Docker's implicit `latest` form without rewriting digests."""
    value = _image_reference(reference)
    if "@" in value:
        return value
    final = value.rsplit("/", 1)[-1]
    return value if ":" in final else f"{value}:latest"


class ProvisionAuthority(IntEnum):
    """Relative specificity used to order competing provider responses."""

    FALLBACK = 0
    DEFAULT = 100
    PREFERRED = 200
    AUTHORITATIVE = 300
    EXPLICIT = 400


@dataclass(frozen=True, slots=True)
class ImageParameter:
    name: str
    value: str

    def __post_init__(self) -> None:
        _nonempty(self.name, label="parameter name")
        if not isinstance(self.value, str) or "\0" in self.value:
            raise ValueError("parameter value must be a NUL-free string")


@dataclass(frozen=True, slots=True)
class ImageRequirement:
    reference: str
    parameters: tuple[ImageParameter, ...] = ()
    origin: str | None = None

    def __post_init__(self) -> None:
        _image_reference(self.reference)
        if type(self.parameters) is not tuple or any(
            not isinstance(item, ImageParameter) for item in self.parameters
        ):
            raise TypeError("requirement parameters must be a tuple of ImageParameter values")
        names = tuple(item.name for item in self.parameters)
        if len(set(names)) != len(names):
            raise ValueError("requirement parameter names must be unique")
        if self.origin is not None:
            _nonempty(self.origin, label="requirement origin")

    @property
    def canonical_reference(self) -> str:
        return canonical_image_reference(self.reference)


def _string_pairs(
    values: tuple[tuple[str, str], ...], *, label: str
) -> tuple[tuple[str, str], ...]:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be a tuple")
    result: list[tuple[str, str]] = []
    for item in values:
        if type(item) is not tuple or len(item) != 2:
            raise TypeError(f"{label} entries must be two-item tuples")
        name, value = item
        normalized_name = _nonempty(name, label=f"{label} name")
        if not isinstance(value, str) or "\0" in value:
            raise ValueError(f"{label} value must be a NUL-free string")
        result.append((normalized_name, value))
    names = tuple(name for name, _ in result)
    if len(set(names)) != len(names):
        raise ValueError(f"{label} names must be unique")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DockerfileRecipe:
    dockerfile: Path
    context: Path
    build_args: tuple[tuple[str, str], ...] = ()
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.dockerfile, Path) or not self.dockerfile.is_absolute():
            raise ValueError("Dockerfile path must be absolute")
        if not isinstance(self.context, Path) or not self.context.is_absolute():
            raise ValueError("Docker build context path must be absolute")
        object.__setattr__(
            self,
            "build_args",
            _string_pairs(self.build_args, label="Docker build arguments"),
        )
        if type(self.extra_args) is not tuple or any(
            not isinstance(value, str) or "\0" in value for value in self.extra_args
        ):
            raise TypeError("extra Docker arguments must be a tuple of NUL-free strings")


@dataclass(frozen=True, slots=True)
class DockerPullRecipe:
    """Pull one source reference and retag it as the provisioned image when needed."""

    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", canonical_image_reference(self.source))


type ImageRecipe = DockerfileRecipe | DockerPullRecipe


@dataclass(frozen=True, slots=True)
class ImageProvision:
    image: str
    recipe: ImageRecipe
    dependencies: tuple[ImageRequirement, ...] = ()
    origin: str | None = None

    def __post_init__(self) -> None:
        _image_reference(self.image, label="provision image")
        if not isinstance(self.recipe, (DockerfileRecipe, DockerPullRecipe)):
            raise TypeError("provision recipe must be a DockerfileRecipe or DockerPullRecipe")
        if type(self.dependencies) is not tuple or any(
            not isinstance(item, ImageRequirement) for item in self.dependencies
        ):
            raise TypeError("provision dependencies must be ImageRequirement values")
        if self.origin is not None:
            _nonempty(self.origin, label="provision origin")

    @property
    def canonical_image(self) -> str:
        return canonical_image_reference(self.image)


@dataclass(frozen=True, slots=True)
class ImageProviderResponse:
    provision: ImageProvision | None = None
    rejection: str | None = None
    authority: ProvisionAuthority = ProvisionAuthority.DEFAULT
    terminal: bool = False
    fallback_on_failure: bool = True

    def __post_init__(self) -> None:
        if (self.provision is None) == (self.rejection is None):
            raise ValueError("provider response must contain exactly one provision or rejection")
        if self.rejection is not None:
            _nonempty(self.rejection, label="provider rejection")
        if not isinstance(self.authority, ProvisionAuthority):
            raise TypeError("provider response authority must be a ProvisionAuthority")
        if type(self.terminal) is not bool:
            raise TypeError("provider response terminal must be a boolean")
        if type(self.fallback_on_failure) is not bool:
            raise TypeError("provider response fallback_on_failure must be a boolean")
        if self.provision is not None and self.terminal:
            raise ValueError("an offered provision cannot be a terminal rejection")

    @classmethod
    def offer(
        cls,
        provision: ImageProvision,
        *,
        authority: ProvisionAuthority = ProvisionAuthority.DEFAULT,
        fallback_on_failure: bool = True,
    ) -> ImageProviderResponse:
        return cls(
            provision=provision,
            authority=authority,
            fallback_on_failure=fallback_on_failure,
        )

    @classmethod
    def reject(
        cls,
        reason: str,
        *,
        authority: ProvisionAuthority = ProvisionAuthority.AUTHORITATIVE,
        terminal: bool = True,
    ) -> ImageProviderResponse:
        return cls(rejection=reason, authority=authority, terminal=terminal)


@runtime_checkable
class ImageProvider(Protocol):
    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
        """Return an offer, a ranked rejection, or no opinion."""


@dataclass(frozen=True, slots=True)
class RegisteredImageProvider:
    provider_id: str
    provider: ImageProvider
    priority: int = 50

    def __post_init__(self) -> None:
        validate_global_identifier(self.provider_id, label="provider ID")
        if not isinstance(self.provider, ImageProvider):
            raise TypeError("provider must implement provide(requirement)")
        if type(self.priority) is not int:
            raise TypeError("provider priority must be an integer")


@dataclass(frozen=True, slots=True)
class ImageBuildGraph:
    roots: tuple[ImageRequirement, ...]
    provisions: tuple[ImageProvision, ...] = ()

    def __post_init__(self) -> None:
        if type(self.roots) is not tuple or any(
            not isinstance(item, ImageRequirement) for item in self.roots
        ):
            raise TypeError("graph roots must be a tuple of ImageRequirement values")
        if type(self.provisions) is not tuple or any(
            not isinstance(item, ImageProvision) for item in self.provisions
        ):
            raise TypeError("graph provisions must be a tuple of ImageProvision values")


def image_providers(api: InvocationAPI) -> tuple[RegisteredImageProvider, ...]:
    value = api.get_context(IMAGE_PROVIDER_CONTEXT, ())
    if type(value) is not tuple or any(
        not isinstance(item, RegisteredImageProvider) for item in value
    ):
        raise RuntimeError("invalid Docker image provider registry")
    return value


def register_image_provider(api: InvocationAPI, provider: RegisteredImageProvider) -> None:
    current = image_providers(api)
    if any(item.provider_id == provider.provider_id for item in current):
        raise RuntimeError(f"Docker image provider {provider.provider_id!r} is already registered")
    api.set_context(IMAGE_PROVIDER_CONTEXT, (*current, provider))


def image_graphs(api: InvocationAPI) -> tuple[ImageBuildGraph, ...]:
    value = api.get_context(IMAGE_GRAPH_CONTEXT, ())
    if type(value) is not tuple or any(not isinstance(item, ImageBuildGraph) for item in value):
        raise RuntimeError("invalid Docker image graph registry")
    return value


def append_image_graph(api: InvocationAPI, graph: ImageBuildGraph) -> None:
    api.set_context(IMAGE_GRAPH_CONTEXT, (*image_graphs(api), graph))


class DockerImagePlugin(Plugin):
    """Goal-specific adapter base for independently published providers."""

    goal_requirement = DOCKER_IMAGE_GOAL_REQUIREMENT

    def provide_image(
        self, requirement: ImageRequirement, api: InvocationAPI
    ) -> ImageProviderResponse | None:
        del requirement, api
        return None


class ImageProviderPlugin(DockerImagePlugin):
    """Ready-to-publish Docker-image-goal adapter for a pure provider object."""

    def __init__(self, provider_id: str, provider: ImageProvider, *, priority: int = 50) -> None:
        registered = RegisteredImageProvider(provider_id, provider, priority)
        self.plugin_id = registered.provider_id
        self.priority = registered.priority
        self.provider = registered.provider

    def provide_image(
        self, requirement: ImageRequirement, api: InvocationAPI
    ) -> ImageProviderResponse | None:
        del api
        return self.provider.provide(requirement)


def _provide_image(
    plugin: DockerImagePlugin,
    requirement: ImageRequirement,
    api: InvocationAPI,
) -> ImageProviderResponse | None:
    return plugin.provide_image(requirement, api)


PROVIDE_IMAGE_PHASE = GoalPhase(
    phase_id="org.engulf.docker-image.provide",
    order=PluginOrder.PREPROCESS,
    local_callback=_provide_image,
    contribution_type=ImageProviderResponse,
)


def ordered_providers(
    providers: Iterable[RegisteredImageProvider],
) -> tuple[RegisteredImageProvider, ...]:
    values = tuple(providers)
    if any(not isinstance(item, RegisteredImageProvider) for item in values):
        raise TypeError("providers must contain RegisteredImageProvider values")
    return tuple(sorted(values, key=lambda item: (-item.priority, item.provider_id)))
