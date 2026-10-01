"""Shell-only host dependency checks for frozen lab launchers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_clab_lab_parser import effective_nodes
from engulf_clab_schema_api import RequirementKind, RuntimeRequirement
from engulf_docker_image_api import canonical_image_reference

_OPERATIONS = ("deploy", "redeploy", "destroy", "inspect", "exec")


def _vrnetlab_images(document: Mapping[str, Any]) -> set[str]:
    references: set[str] = set()
    for node in effective_nodes(document):
        environment = node.data.get("env", {})
        opted_in = isinstance(environment, Mapping) and any(
            isinstance(name, str)
            and name.endswith("_VRNETLAB_TYPE")
            and isinstance(value, str)
            and value.strip()
            for name, value in environment.items()
        )
        reference = node.data.get("image")
        if opted_in and isinstance(reference, str) and reference:
            try:
                references.add(canonical_image_reference(reference))
            except ValueError:
                references.add(reference)
    return references


def _features(document: Mapping[str, Any]) -> set[str]:
    return {"vrnetlab-image-build"} if _vrnetlab_images(document) else set()


def _artifacts(
    root: Path,
    freeze_metadata: Mapping[str, Any],
    topology_document: Mapping[str, Any],
    artifact_root: Path | None = None,
) -> set[str]:
    artifacts: set[str] = set()
    bundled_root = root if artifact_root is None else artifact_root
    containerlab = bundled_root / "tools" / "containerlab" / "bin" / "containerlab"
    if containerlab.is_file() and containerlab.stat().st_mode & 0o111:
        artifacts.add("containerlab-binary")
    if (bundled_root / "tools" / "vrnetlab" / "common" / "vrnetlab.py").is_file():
        artifacts.add("vrnetlab-source")
    plan = freeze_metadata.get("image_plan")
    entries = plan.get("images") if isinstance(plan, Mapping) else None
    if isinstance(entries, list):
        bundled: set[str] = set()
        for item in entries:
            if not isinstance(item, Mapping) or item.get("action") != "archive":
                continue
            image = item.get("image")
            archive = item.get("archive")
            if not isinstance(image, str) or not isinstance(archive, str):
                continue
            relative_archive = Path(archive)
            if relative_archive.is_absolute() or ".." in relative_archive.parts:
                continue
            if (root / relative_archive).is_file():
                bundled.add(image)
        images = _vrnetlab_images(topology_document)
        if images and images <= bundled:
            artifacts.add("vrnetlab-images")
    return artifacts


def write_host_requirements(
    root: Path,
    requirements: tuple[RuntimeRequirement, ...],
    freeze_metadata: Mapping[str, Any],
    topology_document: Mapping[str, Any],
    *,
    artifact_root: Path | None = None,
) -> None:
    """Resolve schema requirements and write a dependency preflight script."""
    features = _features(topology_document)
    artifacts = _artifacts(root, freeze_metadata, topology_document, artifact_root)
    operations = set(_OPERATIONS)
    operations.update(command for item in requirements for command in item.commands)

    rows: dict[tuple[str, RequirementKind, str], str] = {}
    for item in requirements:
        if item.kind not in {RequirementKind.HOST_TOOL, RequirementKind.HOST_LIBRARY}:
            continue
        if item.topology_features and not (set(item.topology_features) & features):
            continue
        if item.unless_artifacts and (set(item.unless_artifacts) & artifacts):
            continue
        selected = item.commands or tuple(sorted(operations))
        for operation in selected:
            rows.setdefault((operation, item.kind, item.name), item.explanation)

    (root / ".eclab-host-requirements.tsv").write_text(
        "".join(
            f"{operation}\t{kind.value}\t{name}\t{explanation}\n"
            for (operation, kind, name), explanation in sorted(
                rows.items(),
                key=lambda entry: (entry[0][0], entry[0][1].value, entry[0][2]),
            )
        ),
        encoding="utf-8",
    )
    (root / ".eclab-vrnetlab-images.txt").write_text(
        "".join(
            f"{reference}\n"
            for reference in sorted(_vrnetlab_images(topology_document))
        ),
        encoding="utf-8",
    )
    checker = root / ".eclab-check-host-requirements.sh"
    checker.write_text(_checker_script(), encoding="utf-8")
    checker.chmod(0o755)
    dependency_reporter = root / "check-dependencies.sh"
    dependency_reporter.write_text(_dependency_reporter_script(), encoding="utf-8")
    dependency_reporter.chmod(0o755)


def _dependency_reporter_script() -> str:
    return r"""#!/bin/sh
set -eu
case "$0" in */*) root=${0%/*}; [ -n "$root" ] || root=/ ;; *) root=. ;; esac
root=$(CDPATH= cd -- "$root" && pwd)
exec "$root/.eclab-check-host-requirements.sh" report "$@"
"""


def _checker_script() -> str:
    return r"""#!/bin/sh
set -u
case "$0" in */*) root=${0%/*}; [ -n "$root" ] || root=/ ;; *) root=. ;; esac
root=$(CDPATH= cd -- "$root" && pwd)
mode=check
if [ "${1-}" = report ]; then mode=report; shift; fi
operation=
expect_value=0
for argument do
    if [ "$expect_value" -eq 1 ]; then expect_value=0; continue; fi
    case "$argument" in
        -t|--topo|--topology|--name|--runtime|--timeout|--ipv4-subnet|--ipv6-subnet|--network|--max-workers|--eclab-containerlab-bin|--eclab-containerlab-dir|--eclab-vrnetlab-dir)
            expect_value=1
            continue
            ;;
        --*=*) continue ;;
        -*) continue ;;
    esac
    case "$argument" in
        deploy|redeploy|destroy|inspect|exec) operation=$argument; break ;;
    esac
done
if [ "$mode" = check ]; then operation=${operation:-deploy}; fi
failed=0
library_present() {
    library=$1
    for path in /lib/"$library" /lib64/"$library" /usr/lib/"$library" /usr/lib64/"$library" /usr/local/lib/"$library" /lib/*/"$library" /usr/lib/*/"$library" /usr/local/lib/*/"$library"; do
        [ -e "$path" ] && return 0
    done
    return 1
}
containerlab_available() {
    [ -n "${CONTAINERLAB_BIN-}" ] && [ -x "$CONTAINERLAB_BIN" ] && return 0
    if [ -n "${CONTAINERLAB_DIR-}" ]; then
        [ -x "$CONTAINERLAB_DIR/bin/containerlab" ] && return 0
        [ -x "$CONTAINERLAB_DIR/containerlab" ] && return 0
    fi
    command -v containerlab >/dev/null 2>&1 && return 0
    pending=
    for argument do
        case "$argument" in
            --eclab-containerlab-bin=*) binary=${argument#*=}; [ -x "$binary" ] && return 0 ;;
            --eclab-containerlab-bin|--eclab-containerlab-dir) pending=$argument ;;
            *)
                if [ "$pending" = --eclab-containerlab-bin ] && [ -x "$argument" ]; then return 0; fi
                if [ "$pending" = --eclab-containerlab-dir ]; then
                    [ -x "$argument/bin/containerlab" ] && return 0
                    [ -x "$argument/containerlab" ] && return 0
                fi
                pending=
                ;;
        esac
    done
    return 1
}
vrnetlab_images_present() {
    command -v docker >/dev/null 2>&1 || return 1
    [ -f "$root/.eclab-vrnetlab-images.txt" ] || return 1
    while IFS= read -r image || [ -n "$image" ]; do
        [ -n "$image" ] || continue
        docker image inspect "$image" >/dev/null 2>&1 || return 1
    done < "$root/.eclab-vrnetlab-images.txt"
    return 0
}
while IFS="$(printf '\t')" read -r required_operation kind name explanation; do
    [ -n "$required_operation" ] || continue
    if [ "$mode" = report ]; then
        [ -z "$operation" ] || [ "$required_operation" = "$operation" ] || continue
    else
        [ "$required_operation" = "$operation" ] || continue
    fi
    available=0
    case "$kind" in
        host-tool)
            case "$name" in
                go) containerlab_available "$@" && available=1 ;;
                make|qemu-img|qemu-system-x86_64) vrnetlab_images_present && available=1 ;;
            esac
            if [ "$available" -eq 0 ] && command -v "$name" >/dev/null 2>&1; then available=1; fi
            ;;
        host-library) library_present "$name" && available=1 ;;
    esac
    if [ "$available" -eq 0 ]; then
        if [ "$mode" = report ]; then
            printf 'WARNING: missing dependency: %s (%s; required for %s)\n' \
                "$name" "$explanation" "$required_operation"
        else
            printf 'missing dependency for %s: %s (%s)\n' \
                "$operation" "$name" "$explanation" >&2
            failed=1
        fi
    fi
done < "$root/.eclab-host-requirements.tsv"
[ "$mode" = report ] && exit 0
exit "$failed"
"""
