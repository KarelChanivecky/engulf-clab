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

from engulf_api import InvocationAPI, StateStore

from .errors import VrnetlabError
from .logging import info
from .requests import BuildRequest
from .sources import file_sha256, prepared_qcow2
from .state import BuildFingerprint, load_state, save_state
from .vrnetlab import builder_directory, vrnetlab_fingerprint, vrnetlab_root


@dataclass(frozen=True)
class PreparedBuild:
    request: BuildRequest
    qcow2: Path
    builder: Path
    fingerprint: BuildFingerprint


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
        if separator and repository and tag and not any(
            character.isspace() for character in candidate
        ):
            return candidate
    return None


def _remove_image_tag(image: str, *, check: bool) -> None:
    subprocess.run(
        ["docker", "image", "rm", image],
        check=check,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


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
                            "vrnetlab builder completed without creating required image "
                            f"{image}"
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
                _remove_image_tag(target_backup, check=True)
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


def _matching_fingerprint(
    state_store: StateStore,
    image: str,
    fingerprint: BuildFingerprint,
) -> bool:
    with state_store.transaction() as locked:
        return load_state(locked).get(image) == fingerprint


def _record_fingerprint(
    state_store: StateStore,
    image: str,
    fingerprint: BuildFingerprint,
) -> None:
    with state_store.transaction() as locked:
        records = load_state(locked)
        records[image] = fingerprint
        save_state(locked, records)


def _ensure_builder_images(
    builds: Sequence[tuple[str, PreparedBuild]],
) -> tuple[list[tuple[str, PreparedBuild]], list[str]]:
    completed: list[tuple[str, PreparedBuild]] = []
    failures: list[str] = []
    for image, prepared in builds:
        try:
            build_native_image(prepared.qcow2, prepared.builder, image)
            completed.append((image, prepared))
        except (OSError, subprocess.SubprocessError, VrnetlabError) as error:
            failures.append(f"{image}: {error}")
    return completed, failures


def ensure_images(
    requests: Sequence[BuildRequest],
    *,
    api: InvocationAPI,
    checkout_context: object | None,
    state_store: StateStore,
    max_workers: int = 2,
) -> None:
    if not requests:
        return

    _require_command("docker")
    source_requests = [request for request in requests if request.source is not None]
    source_images = {request.image for request in source_requests}

    for image in {request.image for request in requests if request.source is None} - source_images:
        with api.lease(_image_lease(image)):
            if not docker_image_exists(image):
                raise VrnetlabError(
                    f"image {image} is absent and no vrnetlab provider source resolved"
                )
            info(f"using existing image {image}; no source configured")

    if not source_requests:
        return

    _require_command("make")
    root = vrnetlab_root(checkout_context)
    root_fingerprint = vrnetlab_fingerprint(root)

    with ExitStack() as stack:
        prepared_by_image: dict[str, PreparedBuild] = {}
        for request in source_requests:
            assert request.source is not None
            builder = builder_directory(root, request.builder_type)
            qcow2 = stack.enter_context(prepared_qcow2(request.source))
            fingerprint = BuildFingerprint(
                qcow2=file_sha256(qcow2),
                qcow2_name=qcow2.name,
                vrnetlab=root_fingerprint,
                builder_type=request.builder_type,
            )
            prepared = PreparedBuild(
                request=request,
                qcow2=qcow2,
                builder=builder,
                fingerprint=fingerprint,
            )

            previous = prepared_by_image.get(request.image)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise VrnetlabError(
                        f"nodes {previous.request.node_name} and {request.node_name} target "
                        f"{request.image} with conflicting vrnetlab sources or builders"
                    )
                continue
            prepared_by_image[request.image] = prepared

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
        completed: list[tuple[str, PreparedBuild]] = []
        with api.leases(lease_names):
            builds_by_builder: dict[Path, list[tuple[str, PreparedBuild]]] = {}
            for image, prepared in prepared_by_image.items():
                if docker_image_exists(image) and _matching_fingerprint(
                    state_store,
                    image,
                    prepared.fingerprint,
                ):
                    info(f"using existing image {image}; build fingerprints unchanged")
                    continue
                builds_by_builder.setdefault(prepared.builder.resolve(), []).append(
                    (image, prepared)
                )

            if builds_by_builder:
                with ThreadPoolExecutor(
                    max_workers=min(max_workers, len(builds_by_builder))
                ) as executor:
                    futures: tuple[
                        Future[tuple[list[tuple[str, PreparedBuild]], list[str]]], ...
                    ] = tuple(
                        executor.submit(
                            copy_context().run,
                            _ensure_builder_images,
                            tuple(builds),
                        )
                        for builds in builds_by_builder.values()
                    )
                    for future in futures:
                        built, build_failures = future.result()
                        completed.extend(built)
                        failures.extend(build_failures)

            for image, prepared in completed:
                _record_fingerprint(state_store, image, prepared.fingerprint)
                info(f"recorded build fingerprint for {image}")
        if failures:
            raise VrnetlabError("vrnetlab image builds failed: " + "; ".join(failures))
