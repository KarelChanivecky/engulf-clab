"""Describe archive-backed roots and dependency images without loading them."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_clab_freeze_api import ImageInput, ImageSource

from .config import ARCHIVE_ENV, ARCHIVE_REF_ENV, ARCHIVE_RELOAD_ENV, build_requests_from_topology


def image_sources(
    topology: Path, document: dict[str, Any], environment: Mapping[str, str]
) -> tuple[ImageSource, ...]:
    del environment
    return tuple(
        ImageSource(
            image=request.image,
            node=None if request.node_name.startswith("manifest:") else request.node_name,
            kind="archive",
            inputs=(ImageInput(request.archive, ARCHIVE_ENV, artifact=True),),
            controls=(ARCHIVE_ENV, ARCHIVE_REF_ENV, ARCHIVE_RELOAD_ENV),
            source=request.source,
        )
        for request in build_requests_from_topology(topology, document, validate_paths=False)
    )
