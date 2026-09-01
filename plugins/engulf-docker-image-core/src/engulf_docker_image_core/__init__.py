"""Recursive Docker image resolution and dependency-first build execution."""

from .build import (
    DEFAULT_IMAGE_BUILD_JOBS,
    ImageBuildOutcome,
    build_resolved_graph,
    docker_build_command,
    docker_load_command,
    docker_pull_commands,
    loaded_archive_references,
    vrnetlab_build_commands,
)
from .dockerfile import dockerfile_requirements
from .errors import (
    DockerfileAnalysisError,
    DockerImageError,
    ImageBuildError,
    ImageBuildFailure,
    ImageResolutionError,
)
from .goal import DockerImageGoal, GraphLoader
from .provision import DEFAULT_PULL_PROVIDER_ID, provision_image_graph
from .resolver import (
    AttributedImageResponse,
    ProviderLookup,
    ProvisionAttempt,
    ResolvedImage,
    ResolvedImageGraph,
    merge_image_graphs,
    registered_provider_lookup,
    resolve_image_graph,
)

__all__ = [
    "DEFAULT_IMAGE_BUILD_JOBS",
    "DEFAULT_PULL_PROVIDER_ID",
    "AttributedImageResponse",
    "DockerImageError",
    "DockerImageGoal",
    "DockerfileAnalysisError",
    "GraphLoader",
    "ImageBuildError",
    "ImageBuildFailure",
    "ImageBuildOutcome",
    "ImageResolutionError",
    "ProviderLookup",
    "ProvisionAttempt",
    "ResolvedImage",
    "ResolvedImageGraph",
    "build_resolved_graph",
    "docker_build_command",
    "docker_load_command",
    "docker_pull_commands",
    "dockerfile_requirements",
    "loaded_archive_references",
    "merge_image_graphs",
    "provision_image_graph",
    "registered_provider_lookup",
    "resolve_image_graph",
    "vrnetlab_build_commands",
]
