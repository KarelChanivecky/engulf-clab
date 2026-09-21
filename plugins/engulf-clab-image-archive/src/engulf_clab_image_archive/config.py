from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_clab_freeze_api import IMAGE_MANIFEST_ENV, FreezeError
from engulf_clab_freeze_api.manifest import read_image_manifest

from .errors import ImageArchiveError
from .topology import topology_nodes

# Fixed across every edition, matching engulf-clab-wan's LABEL_PREFIX convention:
# labels/env vars must stay portable regardless of the active application's
# product metadata.
LABEL_PREFIX = "ECLAB"
ARCHIVE_ENV = f"{LABEL_PREFIX}_IMAGE_ARCHIVE"
ARCHIVE_REF_ENV = f"{LABEL_PREFIX}_IMAGE_ARCHIVE_REF"
ARCHIVE_RELOAD_ENV = f"{LABEL_PREFIX}_IMAGE_ARCHIVE_RELOAD"

# `docker load` reads an uncompressed tar or a gzip, bzip2, or xz compressed one.
ARCHIVE_SUFFIXES = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)

_IMAGE_VARIABLE_SYNTAX = re.compile(r"\$(?:\$|\{?[A-Za-z_][A-Za-z0-9_]*)")
_TRUE_VALUES = frozenset(("1", "on", "true", "yes"))
_FALSE_VALUES = frozenset(("0", "off", "false", "no"))


@dataclass(frozen=True)
class ArchiveRequest:
    node_name: str
    image: str
    archive: Path
    source: str | None = None
    reload: bool = False


def _optional_string(mapping: Mapping[str, Any], key: str, *, owner: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ImageArchiveError(f"{owner} {key} must be a string")
    value = value.strip()
    return value or None


def _optional_boolean(mapping: Mapping[str, Any], key: str, *, owner: str) -> bool:
    value = mapping.get(key)
    if value is None:
        return False
    if not isinstance(value, str):
        raise ImageArchiveError(f"{owner} {key} must be a boolean string")
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ImageArchiveError(f"{owner} {key} must be one of true, false, 1, 0, yes, no, on, or off")


def _resolve_archive(
    value: str, *, topology_dir: Path, node_name: str, validate: bool = True
) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = topology_dir / path
    resolved = path.resolve()
    if validate and not resolved.name.lower().endswith(ARCHIVE_SUFFIXES):
        raise ImageArchiveError(
            f"node {node_name} {ARCHIVE_ENV} must name a {', '.join(ARCHIVE_SUFFIXES)} "
            f"archive: {resolved}"
        )
    if validate and not resolved.exists():
        raise ImageArchiveError(f"node {node_name} {ARCHIVE_ENV} does not exist: {resolved}")
    if validate and not resolved.is_file():
        raise ImageArchiveError(f"node {node_name} {ARCHIVE_ENV} must name a file: {resolved}")
    return resolved


def _archive_reference(value: str, *, node_name: str) -> str:
    if any(character.isspace() for character in value):
        raise ImageArchiveError(
            f"node {node_name} {ARCHIVE_REF_ENV} must not contain whitespace: {value}"
        )
    if _IMAGE_VARIABLE_SYNTAX.search(value):
        raise ImageArchiveError(
            f"node {node_name} {ARCHIVE_REF_ENV} did not resolve to a literal during "
            f"parsing: {value}"
        )
    return value


def build_requests_from_topology(
    topology_path: Path,
    topology_data: dict[str, Any],
    *,
    validate_paths: bool = True,
) -> list[ArchiveRequest]:
    """Return one request per node that opts into an image archive.

    Paths are resolved against the topology directory. The node image tag is the
    reference the archive must satisfy, so it has to be a literal by this point;
    the parser has already expanded topology environment variables.
    """
    topology_dir = topology_path.resolve().parent
    requests: list[ArchiveRequest] = []
    manifests: dict[Path, tuple[dict[str, Any], str]] = {}

    for node in topology_nodes(topology_data):
        environment = node.data.get("env")
        if environment is None:
            continue
        if not isinstance(environment, Mapping):
            raise ImageArchiveError(f"node {node.name} env must be a YAML mapping")
        owner = f"node {node.name}"
        manifest_value = _optional_string(environment, IMAGE_MANIFEST_ENV, owner=owner)
        if manifest_value:
            manifest = (topology_dir / manifest_value).resolve()
            variables = {
                key: value for key, value in environment.items() if key.startswith("ECLAB_FREEZE_")
            }
            previous = manifests.get(manifest)
            if previous is not None and previous[0] != variables:
                raise ImageArchiveError(
                    f"nodes {previous[1]!r} and {node.name!r} select conflicting "
                    "recipient inputs for the same image manifest"
                )
            if manifest not in manifests:
                manifests[manifest] = (variables, node.name)
                requests.extend(_manifest_requests(manifest, environment))
        archive_value = _optional_string(environment, ARCHIVE_ENV, owner=owner)
        reference_value = _optional_string(environment, ARCHIVE_REF_ENV, owner=owner)
        reload_archive = _optional_boolean(environment, ARCHIVE_RELOAD_ENV, owner=owner)
        if archive_value is None:
            if reference_value is not None or reload_archive:
                raise ImageArchiveError(
                    f"node {node.name} sets {ARCHIVE_REF_ENV} or {ARCHIVE_RELOAD_ENV} "
                    f"but not {ARCHIVE_ENV}"
                )
            continue
        image = _optional_string(node.data, "image", owner=owner)
        if image is None:
            raise ImageArchiveError(f"node {node.name} sets {ARCHIVE_ENV} but has no image tag")
        if _IMAGE_VARIABLE_SYNTAX.search(image):
            raise ImageArchiveError(
                f"node {node.name} image tag did not resolve to a literal during parsing: {image}"
            )
        requests.append(
            ArchiveRequest(
                node_name=node.name,
                image=image,
                archive=_resolve_archive(
                    archive_value,
                    topology_dir=topology_dir,
                    node_name=node.name,
                    validate=validate_paths,
                ),
                source=None
                if reference_value is None
                else _archive_reference(reference_value, node_name=node.name),
                reload=reload_archive,
            )
        )
    return requests


def _manifest_requests(path: Path, environment: Mapping[str, Any]) -> list[ArchiveRequest]:
    try:
        entries = read_image_manifest(path)
    except FreezeError as error:
        raise ImageArchiveError(str(error)) from error
    requests = []
    for entry in entries:
        if entry["action"] != "archive":
            continue
        variable = entry.get("archive_variable")
        value = environment.get(variable) if isinstance(variable, str) else entry.get("archive")
        if not isinstance(value, str) or not value or "$" in value:
            raise ImageArchiveError(
                f"image {entry['image']} requires recipient variable {variable}"
            )
        archive = _resolve_archive(value, topology_dir=path.parent, node_name="manifest")
        source = entry.get("source")
        if source is not None:
            if not isinstance(source, str):
                raise ImageArchiveError("image manifest source must be a string")
            source = _archive_reference(source, node_name="manifest")
        requests.append(
            ArchiveRequest(
                node_name=f"manifest:{entry['image']}",
                image=entry["image"],
                archive=archive,
                source=source,
                reload=True,
            )
        )
    return requests
