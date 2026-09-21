"""Portable image manifest validation shared by freeze and archive consumers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contract import FreezeError


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_image_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise FreezeError("image manifest exceeds the metadata size limit")
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FreezeError(f"cannot read image manifest {path.name}: {error}") from error
    if not isinstance(document, dict) or document.get("format") != 1:
        raise FreezeError("unsupported image manifest format")
    images = document.get("images")
    if not isinstance(images, list):
        raise FreezeError("image manifest needs an images list")
    seen: set[str] = set()
    checked: dict[Path, str] = {}
    for entry in images:
        if not isinstance(entry, dict):
            raise FreezeError("invalid image manifest entry")
        reference = entry.get("image")
        if (
            not isinstance(reference, str)
            or not reference
            or any(c.isspace() for c in reference)
        ):
            raise FreezeError("invalid image manifest reference")
        if reference in seen:
            raise FreezeError(f"duplicate image manifest reference: {reference}")
        seen.add(reference)
        if entry.get("action") not in ("archive", "build", "registry", "external"):
            raise FreezeError(f"invalid image manifest action for {reference}")
        relative = entry.get("archive")
        if entry["action"] != "archive" and (
            relative is not None or entry.get("archive_variable") is not None
        ):
            raise FreezeError(
                f"non-archive image has an archive selection: {reference}"
            )
        if relative is None:
            if entry.get("action") == "archive" and not entry.get("archive_variable"):
                raise FreezeError(f"image manifest archive missing for {reference}")
            variable = entry.get("archive_variable")
            if variable is not None and (
                not isinstance(variable, str)
                or not variable.startswith("ECLAB_FREEZE_")
                or not variable.replace("_", "").isalnum()
            ):
                raise FreezeError(f"invalid recipient archive variable for {reference}")
            continue
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
        ):
            raise FreezeError("image manifest archives must be relative paths")
        archive = (path.parent / relative).resolve()
        if not archive.is_relative_to(path.parent.resolve()) or not archive.is_file():
            raise FreezeError(
                f"image manifest archive is missing or escapes its directory: {reference}"
            )
        expected = entry.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise FreezeError(f"image manifest checksum missing for {reference}")
        if archive not in checked:
            checked[archive] = sha256(archive)
        if checked[archive] != expected:
            raise FreezeError(f"image manifest checksum mismatch for {reference}")
    return images
