from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from contextvars import copy_context
from dataclasses import dataclass
from pathlib import Path

from engulf_api import InvocationAPI
from engulf_clab_vrnetlab_build_api import (
    VrnetlabSourceProvenance,
    VrnetlabSourceProvenanceSnapshot,
)

from .errors import VrnetlabError
from .logging import info, warning
from .provider import VRNETLAB_PROVIDER_ID
from .requests import BuildRequest
from .sources import file_sha256, prepared_qcow2
from .vrnetlab import builder_directory, vrnetlab_root


@dataclass(frozen=True)
class PreparedBuild:
    request: BuildRequest
    qcow2: Path
    builder: Path
    source_sha256: str


def _require_command(command: str) -> None:
    if shutil.which(command) is None:
        raise VrnetlabError(f"missing required command: {command}")


def _run(argv: Sequence[str], *, cwd: Path | None = None) -> None:
    subprocess.run(list(argv), cwd=cwd, check=True)


def docker_image_id(image: str) -> str | None:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None
    image_id = result.stdout.strip()
    return image_id or None


def docker_image_exists(image: str) -> bool:
    return docker_image_id(image) is not None


def _native_image_tag_from_make(builder: Path) -> str | None:
    target = "engulf-print-native-image"
    rule = (
        f"{target}: ; "
        '@printf "%s\\n" "$(if $(VR_NAME),$(REGISTRY)vr-$(VR_NAME),'
        '$(IMG_REPOSITORY)):$(VERSION)"'
    )
    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "--silent",
            f"--eval={rule}",
            target,
        ],
        cwd=builder,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None

    for line in reversed(result.stdout.splitlines()):
        candidate = line.strip()
        repository, separator, tag = candidate.rpartition(":")
        if (
            separator
            and repository
            and tag
            and not any(character.isspace() for character in candidate)
        ):
            return candidate
    return None


def _remove_image_tag(image: str, *, check: bool) -> None:
    subprocess.run(
        ["docker", "image", "rm", image],
        check=check,
        capture_output=True,
        text=True,
    )


def _running_containers_using_image(image: str) -> tuple[str, ...] | None:
    """Best-effort list of running containers based on an image reference."""
    try:
        result = subprocess.run(
            [
                "docker",
                "container",
                "ls",
                "--filter",
                f"ancestor={image}",
                "--format",
                "{{.Names}} ({{.ID}})",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _protect_target_image(image: str) -> str | None:
    if not docker_image_exists(image):
        return None

    backup = f"engulf-clab-vrnetlab-build-backup:{uuid.uuid4().hex}"
    _run(["docker", "tag", image, backup])
    try:
        _run(["docker", "image", "rm", image])
    except subprocess.CalledProcessError:
        _remove_image_tag(backup, check=False)
        raise
    return backup


def _restore_target_image(backup: str, image: str) -> None:
    if docker_image_exists(image):
        _remove_image_tag(image, check=True)
    _run(["docker", "tag", backup, image])
    _remove_image_tag(backup, check=True)


def _move_existing_qcow2(builder: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for candidate in builder.iterdir():
        if candidate.name.lower().endswith(".qcow2") and (
            candidate.is_file() or candidate.is_symlink()
        ):
            shutil.move(str(candidate), str(backup_dir / candidate.name))


def _clean_docker_context(builder: Path) -> None:
    docker_dir = builder / "docker"
    if not docker_dir.is_dir():
        return

    for qcow2 in docker_dir.iterdir():
        if ".qcow2" not in qcow2.name.lower() or not (qcow2.is_file() or qcow2.is_symlink()):
            continue
        try:
            qcow2.unlink()
        except PermissionError as error:
            raise VrnetlabError(
                f"cannot remove stale vrnetlab build artifact {qcow2}; "
                "fix checkout ownership or permissions"
            ) from error


def _restore_builder_qcow2(builder: Path, backup_dir: Path, staged_name: str) -> None:
    staged = builder / staged_name
    if staged.exists() or staged.is_symlink():
        staged.unlink()

    if backup_dir.is_dir():
        for qcow2 in backup_dir.iterdir():
            shutil.move(str(qcow2), str(builder / qcow2.name))


def _cleanup_builder(builder: Path, backup_dir: Path, staged_name: str) -> None:
    cleanup_error: Exception | None = None
    try:
        _clean_docker_context(builder)
    except (OSError, subprocess.SubprocessError, VrnetlabError) as error:
        cleanup_error = error

    try:
        _restore_builder_qcow2(builder, backup_dir, staged_name)
    except OSError as restore_error:
        if cleanup_error is not None:
            raise VrnetlabError(
                f"could not clean vrnetlab Docker context ({cleanup_error}) or restore "
                f"builder qcow2 files ({restore_error})"
            ) from cleanup_error
        raise

    if cleanup_error is not None:
        raise cleanup_error


def build_native_image(qcow2: Path, builder: Path, image: str) -> None:
    with tempfile.TemporaryDirectory(prefix="engulf-clab-vrnetlab-build-build-") as directory:
        work_dir = Path(directory)
        backup_dir = work_dir / "existing-qcow2"
        source_for_staging = qcow2
        if qcow2.resolve().is_relative_to(builder.resolve()):
            source_for_staging = work_dir / qcow2.name
            shutil.copy2(qcow2, source_for_staging)

        target_backup: str | None = None
        operation_error: Exception | None = None
        try:
            _move_existing_qcow2(builder, backup_dir)
            _clean_docker_context(builder)
            shutil.copy2(source_for_staging, builder / qcow2.name)
            target_backup = _protect_target_image(image)

            info(f"building {image} with vrnetlab builder {builder}")
            try:
                _run(["make"], cwd=builder)
                if not docker_image_exists(image):
                    native_image = _native_image_tag_from_make(builder)
                    if native_image is None or not docker_image_exists(native_image):
                        raise VrnetlabError(
                            f"vrnetlab builder completed without creating required image {image}"
                        )
                    info(f"tagging native vrnetlab image {native_image} as {image}")
                    _run(["docker", "tag", native_image, image])
            except (OSError, subprocess.SubprocessError, VrnetlabError) as build_error:
                if target_backup is not None:
                    backup_to_restore = target_backup
                    target_backup = None
                    try:
                        _restore_target_image(backup_to_restore, image)
                    except (OSError, subprocess.SubprocessError, VrnetlabError) as restore_error:
                        raise VrnetlabError(
                            f"build of {image} failed and its previous tag could not be restored: "
                            f"{restore_error}"
                        ) from build_error
                raise

            if target_backup is not None:
                containers = _running_containers_using_image(target_backup)
                if containers:
                    warning(
                        f"built {image} successfully; kept the previous image as "
                        f"{target_backup} because running container(s) still use it: "
                        f"{', '.join(containers)}. Stop or destroy those containers, "
                        f"then remove the backup with 'docker image rm {target_backup}'."
                    )
                else:
                    try:
                        _remove_image_tag(target_backup, check=True)
                    except subprocess.CalledProcessError as error:
                        docker_detail = (
                            error.stderr.strip()
                            if isinstance(error.stderr, str) and error.stderr.strip()
                            else None
                        )
                        if containers is None:
                            reason = "Docker could not confirm whether containers still use it"
                        else:
                            reason = "Docker refused to remove the previous image tag"
                        if docker_detail:
                            reason += f": {docker_detail}"
                        warning(
                            f"built {image} successfully, but retained the previous "
                            f"image as {target_backup}: {reason}. After the old image "
                            f"is no longer needed, remove it with 'docker image rm "
                            f"{target_backup}' (cleanup exited {error.returncode})."
                        )
                # The new requested tag is already in place. Backup cleanup must
                # not roll that successful build back.
                target_backup = None
        except (OSError, subprocess.SubprocessError, VrnetlabError) as error:
            operation_error = error
            raise
        finally:
            target_restore_error: Exception | None = None
            if target_backup is not None:
                backup_to_restore = target_backup
                target_backup = None
                try:
                    _restore_target_image(backup_to_restore, image)
                except (OSError, subprocess.SubprocessError, VrnetlabError) as restore_error:
                    target_restore_error = restore_error

            cleanup_error: Exception | None = None
            try:
                _cleanup_builder(builder, backup_dir, qcow2.name)
            except (OSError, subprocess.SubprocessError, VrnetlabError) as error:
                cleanup_error = error

            secondary_errors = [
                message
                for message in (
                    (
                        f"previous image restoration failed: {target_restore_error}"
                        if target_restore_error is not None
                        else None
                    ),
                    (
                        f"builder cleanup failed: {cleanup_error}"
                        if cleanup_error is not None
                        else None
                    ),
                )
                if message is not None
            ]
            if secondary_errors:
                detail = "; ".join(secondary_errors)
                if operation_error is not None:
                    raise VrnetlabError(f"{operation_error}; {detail}") from operation_error
                raise VrnetlabError(detail) from (target_restore_error or cleanup_error)


def _image_lease(image: str) -> str:
    return f"docker-image:{image}"


def _builder_lease(builder: Path) -> str:
    return f"vrnetlab-builder:{builder.resolve()}"


def _ensure_builder_images(
    builds: Sequence[tuple[str, PreparedBuild]],
) -> list[str]:
    failures: list[str] = []
    for image, prepared in builds:
        try:
            build_native_image(prepared.qcow2, prepared.builder, image)
        except (OSError, subprocess.SubprocessError, VrnetlabError) as error:
            failures.append(f"{image}: {error}")
    return failures


def ensure_images(
    requests: Sequence[BuildRequest],
    *,
    api: InvocationAPI,
    checkout_context: object | None,
    max_workers: int = 2,
) -> VrnetlabSourceProvenanceSnapshot:
    if not requests:
        return VrnetlabSourceProvenanceSnapshot()

    _require_command("docker")
    source_requests = [request for request in requests if request.source is not None]
    source_images = {request.image for request in source_requests}

    for image in {request.image for request in requests if request.source is None} - source_images:
        with api.lease(_image_lease(image)):
            if not docker_image_exists(image):
                raise VrnetlabError(
                    f"image {image} is absent and no vrnetlab provider source resolved"
                )
            info(
                f"using existing image {image}; no source configured and no "
                "vrnetlab image provider selected"
            )

    if not source_requests:
        return VrnetlabSourceProvenanceSnapshot()

    _require_command("make")
    root = vrnetlab_root(checkout_context)

    with ExitStack() as stack:
        prepared_by_image: dict[str, PreparedBuild] = {}
        for request in source_requests:
            assert request.source is not None
            builder = builder_directory(root, request.builder_type)
            qcow2 = stack.enter_context(prepared_qcow2(request.source))
            source_sha256 = file_sha256(qcow2)
            prepared = PreparedBuild(
                request=request,
                qcow2=qcow2,
                builder=builder,
                source_sha256=source_sha256,
            )

            previous = prepared_by_image.get(request.image)
            if previous is not None:
                if (
                    previous.source_sha256 != source_sha256
                    or previous.qcow2.name != qcow2.name
                    or previous.request.builder_type != request.builder_type
                ):
                    raise VrnetlabError(
                        f"nodes {previous.request.node_name} and {request.node_name} target "
                        f"{request.image} with conflicting vrnetlab sources or builders"
                    )
                continue
            prepared_by_image[request.image] = prepared

        for request in source_requests:
            info(
                f"vrnetlab image selection for node {request.node_name}: "
                f"{request.image} from {request.source} "
                f"(source provider {request.source_provider_id or 'unspecified'}; "
                f"image provider {VRNETLAB_PROVIDER_ID})"
            )

        lease_names = tuple(
            sorted(
                {
                    lease
                    for image, prepared in prepared_by_image.items()
                    for lease in (_image_lease(image), _builder_lease(prepared.builder))
                }
            )
        )
        failures: list[str] = []
        with api.leases(lease_names):
            builds_by_builder: dict[Path, list[tuple[str, PreparedBuild]]] = {}
            for image, prepared in prepared_by_image.items():
                builds_by_builder.setdefault(prepared.builder.resolve(), []).append(
                    (image, prepared)
                )

            if builds_by_builder:
                with ThreadPoolExecutor(
                    max_workers=min(max_workers, len(builds_by_builder))
                ) as executor:
                    futures: tuple[
                        Future[list[str]], ...
                    ] = tuple(
                        executor.submit(
                            copy_context().run,
                            _ensure_builder_images,
                            tuple(builds),
                        )
                        for builds in builds_by_builder.values()
                    )
                    for future in futures:
                        failures.extend(future.result())
        if failures:
            raise VrnetlabError("vrnetlab image builds failed: " + "; ".join(failures))

        records = tuple(
            VrnetlabSourceProvenance(
                node_name=request.node_name,
                builder_type=request.builder_type,
                source_provider_id=request.source_provider_id,
                source_sha256=prepared_by_image[request.image].source_sha256,
                source_path=(
                    str(request.source)
                    if request.persist_source_path and request.source is not None
                    else None
                ),
            )
            for request in source_requests
        )
        return VrnetlabSourceProvenanceSnapshot(records)
