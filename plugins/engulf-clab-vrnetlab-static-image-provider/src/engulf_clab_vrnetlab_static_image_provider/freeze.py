"""Describe appliance build inputs without locating or running a builder."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_clab_freeze_api import ImageInput, ImageSource
from engulf_clab_lab_parser import effective_nodes

from .config import build_requests_from_topology


def image_sources(
    topology: Path, document: dict[str, Any], environment: Mapping[str, str]
) -> tuple[ImageSource, ...]:
    authored_sources = {
        node.name: node.data.get("env", {}) for node in effective_nodes(document)
    }

    def has_authored_source(node_name: str) -> bool:
        node_environment = authored_sources.get(node_name)
        if not isinstance(node_environment, Mapping):
            return False
        return any(
            isinstance(value, str) and bool(value.strip())
            for key in (
                "ECLAB_VRNETLAB_IMG_PATH",
                "ECLAB_VM_IMG",
                "ECLAB_VM_SRC",
            )
            for value in (node_environment.get(key),)
        )

    return tuple(
        ImageSource(
            image=request.image,
            node=request.node_name,
            kind="build",
            # Do not invent a prompted env variable when the topology supplied
            # no source; recipients can use --eclab-vrnetlab-image at deploy.
            # Only a topology-authored path participates in freeze input
            # checks. Invocation environment values may supply a build at deploy
            # time, but must not create a synthetic recipient prompt.
            inputs=(
                (ImageInput(request.source, "ECLAB_VRNETLAB_IMG_PATH", artifact=True),)
                if request.source is not None and has_authored_source(request.node_name)
                else ()
            ),
            controls=(
                "ECLAB_VRNETLAB_TYPE",
                "ECLAB_VRNETLAB_IMG_PATH",
                "ECLAB_VM_IMG",
                "ECLAB_VM_SRC",
            ),
            rebuildable=True,
            identity=(request.builder_type,),
        )
        for request in build_requests_from_topology(
            topology, document, environment, allow_unresolved_sources=True
        )
    )
