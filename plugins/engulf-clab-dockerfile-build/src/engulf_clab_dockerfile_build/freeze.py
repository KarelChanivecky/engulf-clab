"""Describe Dockerfile inputs to freeze without invoking build preparation."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_clab_freeze_api import ImageInput, ImageSource
from engulf_clab_lab_parser import effective_nodes
from engulf_docker_image_api import DockerfileRecipe
from engulf_docker_image_core.dockerfile import dockerfile_requirements

from .config import BASE_NODE_ENV, _extra_args, _optional_boolean


def _rebuildable_extra_args(arguments: tuple[str, ...]) -> bool:
    """Only claim completeness for extra flags that add no external inputs."""
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--label":
            if index + 1 == len(arguments):
                return False
            index += 2
        elif argument.startswith("--label="):
            index += 1
        else:
            return False
    return True


def image_sources(
    topology: Path, document: dict[str, Any], environment: Mapping[str, str]
) -> tuple[ImageSource, ...]:
    del environment
    sources = []
    for node in effective_nodes(document):
        env = node.data.get("env", {})
        if not env.get("ECLAB_DOCKERFILE"):
            continue
        inputs = []
        for key in ("ECLAB_DOCKERFILE", "ECLAB_DOCKER_CTX"):
            value = env.get(key)
            path = (topology.parent / str(value)).expanduser().resolve() if value else None
            inputs.append(ImageInput(path, key))
        dockerfile, context = (item.path for item in inputs)
        args = tuple(
            sorted(
                (key.removeprefix("ECLAB_DOCKER_VAR_"), value)
                for key, value in env.items()
                if key.startswith("ECLAB_DOCKER_VAR_")
            )
        )
        extra = _extra_args(env.get("ECLAB_DOCKER_ARGS", ""), node_name=node.name)
        dependencies: tuple[str, ...] = ()
        if dockerfile is not None and dockerfile.is_file() and context is not None:
            dependencies = tuple(
                item.reference
                for item in dockerfile_requirements(
                    DockerfileRecipe(dockerfile, context, args, extra)
                )
            )
        sources.append(
            ImageSource(
                image=node.data["image"],
                node=node.name,
                kind="build",
                inputs=tuple(inputs),
                dependencies=dependencies,
                controls=tuple(sorted(key for key in env if key.startswith("ECLAB_DOCKER"))),
                build_only=_optional_boolean(env, BASE_NODE_ENV, owner=f"node {node.name}"),
                rebuildable=_rebuildable_extra_args(extra),
                # RUN/ADD and arbitrary build flags may need the network. Offline
                # freeze captures the output; it never executes a build to find out.
                identity=(repr(args), repr(extra)),
            )
        )
    return tuple(sources)
