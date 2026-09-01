from __future__ import annotations

from collections.abc import Sequence
from threading import Lock

from engulf_docker_image_api import (
    DockerArchiveRecipe,
    ImageProvider,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    canonical_image_reference,
)

from .config import ArchiveRequest

ARCHIVE_PROVIDER_ID = "org.engulf.docker.image-archive"


class ImageArchiveProvider(ImageProvider):
    """Offer a `docker load` recipe for image references backed by an opted-in node.

    Topology reading and path resolution happen once in `refresh_requests`, called
    from the plugin's `prepare_call` where the topology session is available.
    `provide` is then a thread-safe pure lookup: the docker-image resolver may call
    it from build worker threads with no invocation api.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # canonical image reference -> ArchiveRequest, populated by refresh_requests.
        self._requests: dict[str, ArchiveRequest] = {}

    def refresh_requests(self, requests: Sequence[ArchiveRequest]) -> None:
        with self._lock:
            self._requests = {
                canonical_image_reference(request.image): request for request in requests
            }

    def clear(self) -> None:
        with self._lock:
            self._requests = {}

    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
        with self._lock:
            request = self._requests.get(requirement.canonical_reference)
        if request is None:
            return None
        recipe = DockerArchiveRecipe(
            archive=request.archive,
            source=request.source,
            only_if_missing=not request.reload,
        )
        return ImageProviderResponse.offer(
            ImageProvision(
                requirement.canonical_reference,
                recipe,
                origin=f"image archive node {request.node_name}",
            ),
            authority=ProvisionAuthority.PREFERRED,
            # An explicitly selected archive is the node's declared image source; a
            # public-registry pull of the same tag would be a different image, so a
            # failed load must surface instead of falling through.
            fallback_on_failure=False,
        )
