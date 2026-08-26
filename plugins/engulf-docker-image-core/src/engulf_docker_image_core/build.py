from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from engulf_api import InvocationAPI
from engulf_docker_image_api import DockerfileRecipe, DockerPullRecipe

from .errors import ImageBuildError, ImageBuildFailure
from .resolver import ResolvedImage, ResolvedImageGraph

DEFAULT_IMAGE_BUILD_JOBS = 2
_RESERVED_ARGUMENTS = frozenset(("-f", "--file", "-t", "--tag"))


@dataclass(frozen=True, slots=True)
class ImageBuildOutcome:
    resolved: ResolvedImageGraph
    built: tuple[str, ...]
    external: tuple[str, ...]
    pulled: tuple[str, ...] = ()


def docker_build_command(image: ResolvedImage) -> tuple[str, ...]:
    if image.provision is None:
        raise ValueError("external images do not have Docker build commands")
    recipe = image.provision.recipe
    if not isinstance(recipe, DockerfileRecipe):
        raise TypeError("pull recipes do not have Docker build commands")
    _validate_extra_args(recipe)
    return (
        "docker",
        "build",
        "--file",
        str(recipe.dockerfile),
        "--tag",
        image.image,
        *(
            argument
            for name, value in recipe.build_args
            for argument in ("--build-arg", f"{name}={value}")
        ),
        *recipe.extra_args,
        str(recipe.context),
    )


def docker_pull_commands(image: ResolvedImage) -> tuple[tuple[str, ...], ...]:
    if image.provision is None or not isinstance(image.provision.recipe, DockerPullRecipe):
        raise TypeError("Dockerfile recipes do not have Docker pull commands")
    source = image.provision.recipe.source
    commands: list[tuple[str, ...]] = [("docker", "pull", source)]
    if source != image.image:
        commands.append(("docker", "tag", source, image.image))
    return tuple(commands)


def build_resolved_graph(
    graph: ResolvedImageGraph,
    *,
    api: InvocationAPI,
    max_workers: int = DEFAULT_IMAGE_BUILD_JOBS,
) -> ImageBuildOutcome:
    if type(max_workers) is not int or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    builds = {item.image: item for item in graph.images if not item.external}
    external = tuple(item.image for item in graph.images if item.external)
    if not builds:
        return ImageBuildOutcome(graph, (), external)
    if shutil.which("docker") is None:
        raise ImageBuildError("missing required command: docker")
    for item in builds.values():
        _validate_recipe(item)

    pending = set(builds)
    succeeded: set[str] = set()
    failed: dict[str, str] = {}
    direct_failures: list[ImageBuildFailure] = []
    lease_images = set(builds)
    lease_images.update(
        item.provision.recipe.source
        for item in builds.values()
        if item.provision is not None and isinstance(item.provision.recipe, DockerPullRecipe)
    )
    leases = tuple(f"docker-image:{image}" for image in sorted(lease_images))
    with api.leases(leases):
        while pending:
            blocked = {
                image
                for image in pending
                if any(dependency in failed for dependency in builds[image].dependencies)
            }
            for image in sorted(blocked):
                failed[image] = "a build dependency failed"
            pending.difference_update(blocked)
            ready = tuple(
                sorted(
                    image
                    for image in pending
                    if all(
                        dependency not in builds or dependency in succeeded
                        for dependency in builds[image].dependencies
                    )
                )
            )
            if not ready:
                if pending:
                    raise ImageBuildError(
                        "selected Docker image graph contains an unschedulable dependency cycle"
                    )
                break
            for image in ready:
                item = builds[image]
                assert item.provision is not None
                recipe = item.provision.recipe
                if isinstance(recipe, DockerfileRecipe):
                    api.logger.info("building %s from %s", image, recipe.dockerfile)
                else:
                    api.logger.info("pulling %s from %s", image, recipe.source)
            results = _build_batch(tuple(builds[image] for image in ready), max_workers)
            for item, error in results:
                image = item.image
                if error is None:
                    succeeded.add(image)
                else:
                    failed[image] = error
                    assert item.provision is not None
                    direct_failures.append(
                        ImageBuildFailure(
                            image,
                            item.provider_id or "graph",
                            item.provision,
                            error,
                            item.fallback_on_failure,
                        )
                    )
            pending.difference_update(ready)

    if failed:
        details = "; ".join(f"{image}: {failed[image]}" for image in sorted(failed))
        raise ImageBuildError(
            f"Docker image provisioning failed: {details}",
            failures=tuple(direct_failures),
        )
    built = tuple(
        sorted(
            image
            for image in succeeded
            if _is_dockerfile_build(builds[image])
        )
    )
    pulled = tuple(sorted(set(succeeded) - set(built)))
    return ImageBuildOutcome(graph, built, external, pulled)


def _build_batch(
    images: tuple[ResolvedImage, ...], max_workers: int
) -> tuple[tuple[ResolvedImage, str | None], ...]:
    with ThreadPoolExecutor(max_workers=min(max_workers, len(images))) as executor:
        futures: tuple[tuple[ResolvedImage, Future[None]], ...] = tuple(
            (image, executor.submit(_build_image, image)) for image in images
        )
        results: list[tuple[ResolvedImage, str | None]] = []
        for image, future in futures:
            try:
                future.result()
            except ImageBuildError as error:
                results.append((image, str(error)))
            else:
                results.append((image, None))
        return tuple(results)


def _build_image(image: ResolvedImage) -> None:
    try:
        if image.provision is None:
            raise ImageBuildError("external images cannot be provisioned directly")
        if isinstance(image.provision.recipe, DockerfileRecipe):
            commands: tuple[tuple[str, ...], ...] = (docker_build_command(image),)
        else:
            commands = docker_pull_commands(image)
        for command in commands:
            subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise ImageBuildError(f"exit code {error.returncode}") from error
    except OSError as error:
        raise ImageBuildError(str(error)) from error


def _validate_recipe(image: ResolvedImage) -> None:
    assert image.provision is not None
    recipe = image.provision.recipe
    if isinstance(recipe, DockerPullRecipe):
        return
    if not recipe.dockerfile.is_file():
        raise ImageBuildError(f"Dockerfile does not exist for {image.image}: {recipe.dockerfile}")
    if not recipe.context.is_dir():
        raise ImageBuildError(
            f"Docker build context does not exist for {image.image}: {recipe.context}"
        )
    _validate_extra_args(recipe)


def _is_dockerfile_build(image: ResolvedImage) -> bool:
    return image.provision is not None and isinstance(
        image.provision.recipe, DockerfileRecipe
    )


def _validate_extra_args(recipe: DockerfileRecipe) -> None:
    for argument in recipe.extra_args:
        if argument == "--pull" or (
            argument.startswith("--pull=")
            and argument.removeprefix("--pull=").lower() not in ("false", "0")
        ):
            raise ImageBuildError(
                "Docker recipe must not enable --pull; base images are provisioned "
                "through the image graph"
            )
        if argument in _RESERVED_ARGUMENTS or argument.startswith(("--file=", "--tag=")):
            raise ImageBuildError(
                f"Docker recipe must not override plugin-owned argument {argument}"
            )
        if argument.startswith(("-f", "-t")):
            raise ImageBuildError(
                f"Docker recipe must not override plugin-owned argument {argument}"
            )
