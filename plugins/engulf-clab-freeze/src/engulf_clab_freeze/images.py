"""Plan and capture the image dependency boundary of a portable lab."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from engulf_clab_freeze_api import (
    IMAGE_MANIFEST_ENV,
    FreezeError,
    ImageInput,
    ImageSource,
    discover_image_sources,
)
from engulf_clab_freeze_api.manifest import read_image_manifest, sha256
from engulf_clab_lab_parser import effective_nodes, topology_declarations
from engulf_clab_lab_parser.environment import expand_environment, topology_environment
from engulf_docker_image_api import canonical_image_reference

MANIFEST = "images.freeze.json"


def _run(
    arguments: list[str], *, timeout: float | None = 30
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            arguments, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def inspect_image(reference: str) -> dict[str, Any] | None:
    result = _run(["docker", "image", "inspect", reference])
    if result is None or result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
        return (
            data[0]
            if isinstance(data, list) and data and isinstance(data[0], dict)
            else None
        )
    except ValueError:
        return None


def registry_identity(reference: str, local: Mapping[str, Any] | None) -> str | None:
    """A failed probe is unknown. A different local image must be captured."""
    result = _run(["docker", "manifest", "inspect", "--verbose", reference])
    if result is None or result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    candidates = data if isinstance(data, list) else [data]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        descriptor = candidate.get("Descriptor", {})
        manifest = candidate.get("SchemaV2Manifest", candidate.get("OCIManifest", {}))
        if not isinstance(descriptor, dict) or not isinstance(manifest, dict):
            continue
        digest = descriptor.get("digest")
        config = manifest.get("config", {})
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            continue
        if local is not None and (
            not isinstance(config, dict) or config.get("digest") != local.get("Id")
        ):
            continue
        return digest
    return None


def _staged_input(item: ImageInput, source_root: Path, staging: Path) -> Path | None:
    path = item.path
    if path is not None and path.is_relative_to(staging):
        return path if path.is_file() or path.is_dir() else None
    if path is None or not path.is_relative_to(source_root):
        return None
    target = staging / path.relative_to(source_root)
    if path.is_file():
        return target if target.is_file() else None
    if not path.is_dir() or not target.is_dir():
        return None
    # Conservative completeness: files omitted by freeze may be build inputs.
    # Do not infer COPY/RUN behavior by executing a build or guessing globs.
    for member in path.rglob("*"):
        if member.is_relative_to(staging.parent):
            continue
        if member.is_file() and not (target / member.relative_to(path)).is_file():
            return None
    return target


def _archive_source(
    path: Path, reference: str, selected: str | None
) -> tuple[str | None, str | None]:
    """Validate a saved-image selection without extracting or loading its data."""
    try:
        with tarfile.open(path, "r:*") as archive:
            member = archive.getmember("manifest.json")
            if not member.isfile() or member.size > 8 * 1024 * 1024:
                raise ValueError("invalid saved-image manifest")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("missing saved-image manifest")
            entries = json.load(stream)
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        raise FreezeError(
            f"cannot inspect saved-image archive for {reference}: {error}"
        ) from error
    if not isinstance(entries, list) or not entries:
        raise FreezeError(f"empty saved-image archive for {reference}")
    wanted = canonical_image_reference(selected or reference)
    matches = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise FreezeError(f"invalid saved-image archive for {reference}")
        tags = entry.get("RepoTags") or []
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise FreezeError(f"invalid saved-image tags for {reference}")
        if wanted in {canonical_image_reference(tag) for tag in tags}:
            matches.append(entry)
    if not matches and selected is None and len(entries) == 1:
        matches = entries
    if len(matches) != 1:
        raise FreezeError(
            f"archive does not unambiguously supply {reference}; select its source reference"
        )
    entry = matches[0]
    config = entry.get("Config")
    image_id = Path(config).stem if isinstance(config, str) else None
    if image_id and re.fullmatch(r"[a-f0-9]{64}", image_id):
        image_id = f"sha256:{image_id}"
    else:
        image_id = None
    return selected, image_id


def _variable(reference: str, purpose: str) -> str:
    name = re.sub(r"[^A-Z0-9]+", "_", reference.upper()).strip("_")[:40]
    suffix = hashlib.sha256(f"{reference}:{purpose}".encode()).hexdigest()[:8].upper()
    return f"ECLAB_FREEZE_{name}_{purpose}_{suffix}"


def freeze_images(
    topology_path: Path,
    document: dict[str, Any],
    staging: Path,
    environment: Mapping[str, str],
    *,
    offline: bool = False,
    lean: bool = False,
    external_images: tuple[str, ...] = (),
    bundle_images: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Mutate only a staged topology and its files; never build, pull, or load."""
    if lean and offline:
        raise FreezeError("--lean and --offline cannot be combined")
    source_root = topology_path.parent
    current_env = topology_environment(topology_path, environment)

    # Expand the staged document against the original lab's env, keeping the
    # authored document available for recipient expressions and sanitization.
    def expanded(value: Any) -> Any:
        if isinstance(value, str):
            return expand_environment(value, current_env)
        if isinstance(value, dict):
            return {key: expanded(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expanded(item) for item in value]
        return value

    resolved = expanded(document)
    resolved.pop("x-engulf-clab-freeze", None)
    nodes = {node.name: node for node in effective_nodes(resolved)}
    authored = {node.name: node for node in effective_nodes(document)}
    by_image: dict[str, list[ImageSource]] = {}
    roots: list[str] = []
    for node in nodes.values():
        reference = node.data.get("image")
        if reference is None:
            continue
        if (
            not isinstance(reference, str)
            or not reference
            or any(char.isspace() for char in reference)
        ):
            raise FreezeError(f"node {node.name} has an invalid image reference")
        if "$" in reference:
            if lean:
                resolved["topology"]["nodes"].pop(node.name, None)
                continue
            raise FreezeError(f"node {node.name} image must resolve before freeze")
        roots.append(canonical_image_reference(reference))
    sources = discover_image_sources(topology_path, resolved, current_env)
    dependencies = {
        canonical_image_reference(item)
        for source in sources
        for item in source.dependencies
    }
    for source in sources:
        reference = canonical_image_reference(source.image)
        normalized = replace(source, image=reference)
        previous = by_image.setdefault(reference, [])
        if previous and replace(previous[0], node=None, build_only=False) != replace(
            normalized, node=None, build_only=False
        ):
            raise FreezeError(f"conflicting acquisition recipes for {reference}")
        previous.append(normalized)

    # Flatten owned controls first, then remove every inherited/shadowed origin.
    # This prevents an exported node from accidentally re-enabling its old build.
    owned = {key for source in sources for key in source.controls} | {
        IMAGE_MANIFEST_ENV
    }
    raw_nodes = document["topology"]["nodes"]
    for declaration in topology_declarations(document):
        owner: Any = document
        for part in declaration.origin.path:
            owner = owner[part]
        env = owner.get("env", {})
        if isinstance(env, dict):
            for key in owned:
                env.pop(key, None)
    for name, node in authored.items():
        definition = raw_nodes.setdefault(name, {})
        if definition is None:
            definition = raw_nodes[name] = {}
        values = {
            key: value
            for key, value in node.data.get("env", {}).items()
            if key in owned and key != IMAGE_MANIFEST_ENV
        }
        if values:
            definition.setdefault("env", {}).update(values)

    try:
        external = {canonical_image_reference(item) for item in external_images}
        forced = {canonical_image_reference(item) for item in bundle_images}
    except (ValueError, TypeError) as error:
        raise FreezeError(f"invalid image override: {error}") from error
    if external & forced:
        raise FreezeError("an image cannot be both external and forced into the bundle")
    if offline and external:
        raise FreezeError("--external-image cannot be combined with --offline")
    if lean and forced:
        raise FreezeError("--bundle-image cannot be combined with --lean")
    entries: dict[str, dict[str, Any]] = {}
    visiting: list[str] = []
    copied: dict[str, str] = {}
    variables: dict[str, str] = {}

    def owners(reference: str) -> list[str]:
        return [
            name
            for name, node in nodes.items()
            if isinstance(node.data.get("image"), str)
            and canonical_image_reference(node.data["image"]) == reference
        ]

    def disable(reference: str) -> None:
        for source in by_image.get(reference, []):
            if source.node is None:
                continue
            if source.build_only:
                raw_nodes.pop(source.node, None)
                continue
            env = raw_nodes[source.node].get("env", {})
            for control in source.controls:
                env.pop(control, None)
        for name in owners(reference):
            if name in raw_nodes:
                raw_nodes[name]["image"] = reference

    def relative_input(item: ImageInput) -> str | None:
        path = _staged_input(item, source_root, staging)
        return path.relative_to(staging).as_posix() if path is not None else None

    def plan(reference: str) -> None:
        reference = canonical_image_reference(reference)
        if reference in visiting:
            raise FreezeError(
                "image dependency cycle: " + " -> ".join((*visiting, reference))
            )
        if reference in entries:
            return
        visiting.append(reference)
        declarations = by_image.get(reference, [])
        source = (
            declarations[0] if declarations else ImageSource(reference, None, "opaque")
        )
        entry: dict[str, Any] = {"image": reference, "nodes": owners(reference)}
        entries[reference] = entry
        portable = (
            source.kind == "build"
            and source.rebuildable
            and all(relative_input(item) is not None for item in source.inputs)
            and (not offline or source.offline_rebuildable)
        )
        lean_inputs = (
            lean
            and source.inputs
            and (
                source.kind == "archive"
                or not portable
                or any(item.artifact for item in source.inputs)
            )
        )
        if reference in external:
            entry.update(
                action="external", reason="recipient supplies this image explicitly"
            )
            disable(reference)
        elif lean_inputs:
            entry.update(
                action="external", reason="recipient supplies acquisition inputs"
            )
            for item in source.inputs:
                if not item.artifact and relative_input(item) is not None:
                    value = relative_input(item)
                else:
                    variable = _variable(reference, item.control.removeprefix("ECLAB_"))
                    value = "${" + variable + "}"
                    if source.node is not None:
                        original = (
                            authored[source.node].data.get("env", {}).get(item.control)
                        )
                        if isinstance(original, str) and re.fullmatch(
                            r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})",
                            original,
                        ):
                            value = original
                    # Inputs intentionally omitted from a lean archive must not
                    # survive as incidental files copied with the source tree.
                    staged = _staged_input(item, source_root, staging)
                    if item.artifact and staged is not None and staged.is_file():
                        staged.unlink()
                for declaration in declarations:
                    if declaration.node is not None:
                        raw_nodes[declaration.node].setdefault("env", {})[
                            item.control
                        ] = value
                if source.node is None:
                    variable = _variable(reference, "ARCHIVE")
                    variables[variable] = "${" + variable + "}"
                    entry.update(
                        action="archive",
                        archive_variable=variable,
                        source=source.source,
                    )
            for dependency in source.dependencies:
                plan(dependency)
        elif portable and reference not in forced:
            entry.update(
                action="build",
                reason="recipe and file inputs are included",
                dependencies=list(source.dependencies),
            )
            for declaration in declarations:
                if declaration.node is not None:
                    raw_nodes[declaration.node]["image"] = reference
                    env = raw_nodes[declaration.node].setdefault("env", {})
                    if not lean:
                        effective_env = nodes[declaration.node].data.get("env", {})
                        env.update(
                            {
                                key: effective_env[key]
                                for key in declaration.controls
                                if key in effective_env
                            }
                        )
                    for item in declaration.inputs:
                        env[item.control] = relative_input(item)
            for dependency in source.dependencies:
                plan(dependency)
        elif source.kind == "archive" and reference not in forced:
            require_archive_tag(reference)
            path = source.inputs[0].path if source.inputs else None
            if path is None or not path.is_file():
                capture(reference, entry)
                visiting.pop()
                return
            selected, image_id = _archive_source(path, reference, source.source)
            checksum = sha256(path)
            relative = copied.get(checksum)
            if relative is None:
                relative = relative_input(source.inputs[0])
                if relative is None:
                    # An excluded lab-local artifact stays excluded. Export its
                    # loaded image instead of bypassing the author's exclusions.
                    if path.is_relative_to(source_root):
                        capture(reference, entry)
                        visiting.pop()
                        return
                    suffix = "".join(path.suffixes) or ".tar"
                    relative = f"images/{checksum}{suffix}"
                    target = staging / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and sha256(target) != checksum:
                        raise FreezeError("bundled image path collides with a lab file")
                    shutil.copy2(path, target)
                copied[checksum] = relative
            entry.update(
                action="archive",
                archive=relative,
                sha256=checksum,
                source=selected,
                image_id=image_id,
                reason="declared saved-image source",
            )
            disable(reference)
        else:
            local = inspect_image(reference)
            remote = None
            if (
                not offline
                and reference not in forced
                and source.kind in ("registry", "opaque")
            ):
                remote = registry_identity(source.source or reference, local)
            if remote is not None:
                entry.update(
                    action="registry",
                    source=source.source or reference,
                    digest=remote,
                    reason="registry supplies the selected image",
                )
            elif lean:
                disable(reference)
                names = owners(reference)
                if names and reference not in dependencies:
                    variable = _variable(reference, "IMAGE")
                    for name in names:
                        if name in raw_nodes:
                            raw_nodes[name]["image"] = "${" + variable + "}"
                    entry.update(
                        action="external", reason="recipient selects the image"
                    )
                else:
                    require_archive_tag(reference)
                    variable = _variable(reference, "ARCHIVE")
                    variables[variable] = "${" + variable + "}"
                    entry.update(
                        action="archive",
                        archive_variable=variable,
                        reason="recipient supplies a build dependency archive",
                    )
            else:
                capture(reference, entry, local)
        visiting.pop()

    def capture(
        reference: str, entry: dict[str, Any], local: dict[str, Any] | None = None
    ) -> None:
        require_archive_tag(reference)
        local = local or inspect_image(reference)
        if local is None or not isinstance(local.get("Id"), str):
            chain = " -> ".join(visiting)
            raise FreezeError(
                f"cannot package image {reference} ({chain}): no usable archive, complete recipe, verified registry source, or local image; supply it first or use --lean/--external-image"
            )
        image_id = local["Id"]
        identity = hashlib.sha256(image_id.encode()).hexdigest()
        relative = copied.get(image_id)
        if relative is None:
            relative = f"images/{identity}.tar"
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FreezeError("exported image path collides with a lab file")
            # Save by immutable ID: a concurrently retagged image must not change
            # the selected content. The archive provider retags its single image.
            result = _run(
                ["docker", "image", "save", "--output", str(target), image_id],
                timeout=None,
            )
            if result is None or result.returncode or not target.is_file():
                raise FreezeError(f"Docker could not export {reference}")
            copied[image_id] = relative
        entry.update(
            action="archive",
            archive=relative,
            sha256=sha256(staging / relative),
            image_id=image_id,
            platform="/".join(
                str(local.get(key, "")) for key in ("Os", "Architecture", "Variant")
            ).rstrip("/"),
            reason="selected image cannot be obtained or rebuilt from the bundle",
        )
        disable(reference)

    def require_archive_tag(reference: str) -> None:
        if "@" in reference:
            raise FreezeError(
                f"cannot restore digest reference {reference} by retagging an archive; "
                "select a tag before freezing, or use --external-image"
            )

    for root in dict.fromkeys(roots):
        plan(root)
    unused = (external | forced) - entries.keys()
    if unused:
        raise FreezeError(
            "image override does not match a dependency: " + ", ".join(sorted(unused))
        )
    manifest = {"format": 1, "images": [entries[key] for key in sorted(entries)]}
    destination = staging / MANIFEST
    if destination.exists():
        # Refreezing a recognized bundle replaces its generated manifest only.
        read_image_manifest(destination)
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if any(entry["action"] == "archive" for entry in entries.values()):
        for definition in raw_nodes.values():
            definition.setdefault("env", {}).update(
                {IMAGE_MANIFEST_ENV: MANIFEST, **variables}
            )
    return {"manifest": MANIFEST, "lean": lean, "images": manifest["images"]}
