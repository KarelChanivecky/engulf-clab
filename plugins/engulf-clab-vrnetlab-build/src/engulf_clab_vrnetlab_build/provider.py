from __future__ import annotations

from collections.abc import Sequence
from threading import Lock

from engulf_docker_image_api import (
    ImageProvider,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    VrnetlabBuildRecipe,
)

from .config import BuildRequest
from .errors import VrnetlabError
from .vrnetlab import builder_directory, vrnetlab_root

VRNETLAB_PROVIDER_ID = "org.engulf.docker.vrnetlab-build"


class VrnetlabBuildProvider(ImageProvider):
    """Offer a vrnetlab build for image references backed by an opted-in topology node.

    The expensive, api-touching discovery (resolving sources, locating the builder
    directory) happens once in `refresh_requests`, called from the plugin's
    `prepare_call` which has the topology session and invocation context. `provide`
    is then a thread-safe pure lookup — the docker-image resolver may call it from
    build worker threads with no invocation api.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # image reference -> BuildRequest, populated by refresh_requests.
        self._requests: dict[str, BuildRequest] = {}
        self._checkout_context: object | None = None

    def refresh_requests(
        self,
        requests: Sequence[BuildRequest],
        *,
        checkout_context: object | None,
    ) -> None:
        with self._lock:
            self._requests = {request.image: request for request in requests}
            self._checkout_context = checkout_context

    def clear(self) -> None:
        with self._lock:
            self._requests = {}
            self._checkout_context = None

    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
        reference = requirement.reference
        with self._lock:
            request = self._requests.get(reference)
            checkout_context = self._checkout_context
        if request is None:
            return None
        # A node opted into vrnetlab with no resolvable source cannot be built here;
        # fall through with no opinion so the pull fallback (or nothing) applies.
        if request.source is None:
            return None
        try:
            root = vrnetlab_root(checkout_context)
            builder = builder_directory(root, request.builder_type)
        except (VrnetlabError, OSError) as error:
            return ImageProviderResponse.reject(
                f"cannot resolve vrnetlab builder for {reference}: {error}",
                authority=ProvisionAuthority.AUTHORITATIVE,
                terminal=False,
            )
        recipe = VrnetlabBuildRecipe(
            source=request.source,
            builder=builder,
            image=reference,
        )
        return ImageProviderResponse.offer(
            ImageProvision(reference, recipe, origin=f"vrnetlab node {request.node_name}"),
            authority=ProvisionAuthority.PREFERRED,
            fallback_on_failure=True,
        )
