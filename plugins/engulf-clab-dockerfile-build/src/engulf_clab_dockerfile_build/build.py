from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor

from engulf_api import InvocationAPI

from .config import DEFAULT_DOCKER_BUILD_JOBS, BuildRequest
from .errors import DockerfileError


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise DockerfileError("missing required command: docker")


def _command(request: BuildRequest) -> tuple[str, ...]:
    return (
        "docker",
        "build",
        "--file",
        str(request.dockerfile),
        "--tag",
        request.image,
        *(argument for name, value in request.build_args for argument in ("--build-arg", f"{name}={value}")),
        *request.extra_args,
        str(request.context),
    )


def _coalesced(requests: Sequence[BuildRequest]) -> tuple[BuildRequest, ...]:
    by_image: dict[str, BuildRequest] = {}
    for request in requests:
        previous = by_image.get(request.image)
        if previous is None:
            by_image[request.image] = request
        elif _definition(previous) != _definition(request):
            raise DockerfileError(
                f"nodes {previous.node_name} and {request.node_name} declare conflicting "
                f"Dockerfile builds for image {request.image}"
            )
    return tuple(by_image.values())


def _definition(request: BuildRequest) -> tuple[object, ...]:
    """Return the build-affecting fields, excluding the declaring node name."""
    return (
        request.image,
        request.dockerfile,
        request.context,
        request.build_args,
        request.extra_args,
    )


def _build_image(request: BuildRequest) -> None:
    command = _command(request)
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise DockerfileError(
            f"Docker build for {request.image} failed with exit code {error.returncode}"
        ) from error


def build_images(
    requests: Sequence[BuildRequest],
    *,
    api: InvocationAPI,
    max_workers: int = DEFAULT_DOCKER_BUILD_JOBS,
) -> None:
    if not requests:
        return
    _require_docker()
    builds = _coalesced(requests)
    failures: list[str] = []
    leases = tuple(f"docker-image:{request.image}" for request in builds)
    with api.leases(leases):
        with ThreadPoolExecutor(max_workers=min(max_workers, len(builds))) as executor:
            futures: tuple[Future[None], ...] = tuple(
                executor.submit(_build_image, request) for request in builds
            )
            for request in builds:
                api.logger.info("building %s from %s", request.image, request.dockerfile)
            for future in futures:
                try:
                    future.result()
                except DockerfileError as error:
                    failures.append(str(error))
    if failures:
        raise DockerfileError("Docker image builds failed: " + "; ".join(failures))
