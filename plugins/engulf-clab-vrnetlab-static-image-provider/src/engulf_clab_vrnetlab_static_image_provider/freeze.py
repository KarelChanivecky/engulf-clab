"""Describe appliance build inputs without locating or running a builder."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_clab_freeze_api import ImageInput, ImageSource

from .config import build_requests_from_topology


def image_sources(
    topology: Path, document: dict[str, Any], environment: Mapping[str, str]
) -> tuple[ImageSource, ...]:
    return tuple(
        ImageSource(
            image=request.image,
            node=request.node_name,
            kind="build",
            inputs=(ImageInput(request.source, "ECLAB_VRNETLAB_IMG_PATH", artifact=True),),
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
