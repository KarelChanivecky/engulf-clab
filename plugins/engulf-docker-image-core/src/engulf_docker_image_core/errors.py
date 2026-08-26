from __future__ import annotations

from dataclasses import dataclass

from engulf_docker_image_api import ImageProvision


class DockerImageError(RuntimeError):
    """Base error for image resolution and build execution."""


class DockerfileAnalysisError(DockerImageError):
    """A Dockerfile could not be inspected safely."""


class ImageResolutionError(DockerImageError):
    """No consistent recursive image plan could be selected."""


@dataclass(frozen=True, slots=True)
class ImageBuildFailure:
    image: str
    provider_id: str
    provision: ImageProvision
    reason: str
    fallback_on_failure: bool


class ImageBuildError(DockerImageError):
    """One or more selected image recipes failed to build."""

    def __init__(
        self,
        message: str,
        *,
        failures: tuple[ImageBuildFailure, ...] = (),
    ) -> None:
        super().__init__(message)
        self.failures = failures
