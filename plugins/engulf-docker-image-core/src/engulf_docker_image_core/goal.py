from __future__ import annotations

from collections.abc import Callable

from engulf_api import Goal, GoalAPI, GoalContract, GoalResult, Invocation
from engulf_docker_image_api import (
    DOCKER_IMAGE_GOAL_REQUIREMENT,
    PROVIDE_IMAGE_PHASE,
    DockerImagePlugin,
    ImageBuildGraph,
    ImageRequirement,
)

from .build import DEFAULT_IMAGE_BUILD_JOBS, ImageBuildOutcome
from .errors import DockerImageError
from .provision import provision_image_graph
from .resolver import AttributedImageResponse

GraphLoader = Callable[[Invocation], ImageBuildGraph]


class DockerImageGoal(Goal[ImageBuildOutcome]):
    """Engulf goal whose application supplies only the root-graph loader."""

    _contract = GoalContract(DOCKER_IMAGE_GOAL_REQUIREMENT, DockerImagePlugin)

    def __init__(self, loader: GraphLoader, *, max_workers: int = DEFAULT_IMAGE_BUILD_JOBS) -> None:
        if not callable(loader):
            raise TypeError("loader must be callable")
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        self._loader = loader
        self._max_workers = max_workers

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def achieve(self, invocation: Invocation, api: GoalAPI) -> GoalResult[ImageBuildOutcome]:
        try:
            graph = self._loader(invocation)

            def lookup(
                requirement: ImageRequirement,
            ) -> tuple[AttributedImageResponse, ...]:
                return tuple(
                    AttributedImageResponse(item.plugin_id, item.value)
                    for item in api.dispatch(PROVIDE_IMAGE_PHASE, requirement)
                )

            return GoalResult.completed(
                provision_image_graph(
                    graph,
                    api=api,
                    provider_lookup=lookup,
                    max_workers=self._max_workers,
                )
            )
        except (DockerImageError, OSError, ValueError, TypeError) as error:
            api.logger.error("%s", error)
            return GoalResult.failed(1, error=str(error))
