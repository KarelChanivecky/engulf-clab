from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
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
from .errors import ImageArchiveError

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
        prepared: dict[str, ArchiveRequest] = {}
        fingerprints: dict[Path, str] = {}
        for request in requests:
            reference = canonical_image_reference(request.image)
            previous = prepared.get(reference)
            if previous is not None and not _compatible_requests(
                previous, request, fingerprints
            ):
                raise ImageArchiveError(
                    f"conflicting image archive declarations for {reference}: "
                    f"node {previous.node_name!r} uses {previous.archive}, "
                    f"node {request.node_name!r} uses {request.archive}"
                )
            prepared.setdefault(reference, request)
        with self._lock:
            self._requests = prepared

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


def _compatible_requests(
    first: ArchiveRequest,
    second: ArchiveRequest,
    fingerprints: dict[Path, str],
) -> bool:
    """Allow shared tags only when the complete archive recipe is identical."""
    if first.archive != second.archive:
        return False
    if first.source != second.source or first.reload != second.reload:
        return False
    first_fingerprint = _archive_fingerprint(first.archive, fingerprints)
    second_fingerprint = _archive_fingerprint(second.archive, fingerprints)
    return first_fingerprint == second_fingerprint


def _archive_fingerprint(path: Path, fingerprints: dict[Path, str]) -> str:
    existing = fingerprints.get(path)
    if existing is not None:
        return existing
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ImageArchiveError(f"cannot fingerprint image archive {path}: {error}") from error
    value = digest.hexdigest()
    fingerprints[path] = value
    return value
