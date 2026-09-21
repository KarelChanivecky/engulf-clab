"""Read-only image portability declarations, independent of recipe execution."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .contract import FreezeError

IMAGE_SOURCE_GROUP = "engulf_clab.freeze.images.v1"
IMAGE_MANIFEST_ENV = "ECLAB_IMAGE_ARCHIVE_MANIFEST"


@dataclass(frozen=True)
class ImageInput:
    """A required file/tree and the node environment key that selects it."""

    path: Path | None
    control: str
    artifact: bool = False

    def __post_init__(self) -> None:
        if self.path is not None and (
            not isinstance(self.path, Path) or not self.path.is_absolute()
        ):
            raise ValueError("image input path must be absolute or None")
        if not isinstance(self.control, str) or not self.control:
            raise ValueError("image input needs an environment control")
        if type(self.artifact) is not bool:
            raise TypeError("image input artifact must be a boolean")


@dataclass(frozen=True)
class ImageSource:
    """Facts supplied by the feature that owns an image's acquisition recipe.

    Discovery must not build, pull, load, probe a registry, or mutate files.
    ``controls`` names the env keys disabled when a finished image replaces
    this recipe. Dependencies describe image inputs, separately from files.
    Opaque/unknown recipes default to non-rebuildable, including offline.
    """

    image: str
    node: str | None
    kind: Literal["build", "archive", "registry", "opaque"]
    inputs: tuple[ImageInput, ...] = ()
    dependencies: tuple[str, ...] = ()
    controls: tuple[str, ...] = ()
    source: str | None = None
    build_only: bool = False
    rebuildable: bool = False
    offline_rebuildable: bool = False
    identity: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.image, str)
            or not self.image
            or "$" in self.image
            or any(char.isspace() for char in self.image)
        ):
            raise ValueError("image source needs a literal image reference")
        if self.kind not in ("build", "archive", "registry", "opaque"):
            raise ValueError("unsupported image acquisition kind")
        for name in ("inputs", "dependencies", "controls", "identity"):
            if type(getattr(self, name)) is not tuple:
                raise TypeError(f"image source {name} must be a tuple")
        if any(not isinstance(item, ImageInput) for item in self.inputs):
            raise TypeError("image source inputs must be ImageInput values")
        for name in ("dependencies", "controls", "identity"):
            if any(not isinstance(item, str) for item in getattr(self, name)):
                raise TypeError(f"image source {name} must contain strings")
        for name in ("build_only", "rebuildable", "offline_rebuildable"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"image source {name} must be a boolean")


def discover_image_sources(
    topology: Path, document: dict[str, Any], environment: Mapping[str, str]
) -> tuple[ImageSource, ...]:
    """Ask installed image owners for portability facts without preparing deploy."""
    sources: list[ImageSource] = []
    for entry in sorted(
        importlib.metadata.entry_points(group=IMAGE_SOURCE_GROUP),
        key=lambda item: item.name,
    ):
        try:
            declared = tuple(entry.load()(topology, document, environment))
            if any(not isinstance(source, ImageSource) for source in declared):
                raise TypeError("expected ImageSource declarations")
        except Exception as error:
            raise FreezeError(
                f"image source discovery failed for {entry.name}: {error}"
            ) from error
        sources.extend(declared)
    return tuple(sources)
