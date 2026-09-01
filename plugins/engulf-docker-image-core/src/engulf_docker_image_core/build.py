from __future__ import annotations

import shutil
import subprocess
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from engulf_api import InvocationAPI
from engulf_docker_image_api import (
    DockerArchiveRecipe,
    DockerfileRecipe,
    DockerPullRecipe,
    VrnetlabBuildRecipe,
    canonical_image_reference,
)

from .errors import ImageBuildError, ImageBuildFailure
from .resolver import ResolvedImage, ResolvedImageGraph

DEFAULT_IMAGE_BUILD_JOBS = 2
_RESERVED_ARGUMENTS = frozenset(("-f", "--file", "-t", "--tag"))
_LOADED_IMAGE_PREFIX = "Loaded image: "
_LOADED_IMAGE_ID_PREFIX = "Loaded image ID: "


@dataclass(frozen=True, slots=True)
class ImageBuildOutcome:
    resolved: ResolvedImageGraph
    built: tuple[str, ...]
    external: tuple[str, ...]
    pulled: tuple[str, ...] = ()
    reused: tuple[str, ...] = ()
    loaded: tuple[str, ...] = ()


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


def docker_load_command(recipe: DockerArchiveRecipe) -> tuple[str, ...]:
    """Return the `docker load` command for one archive recipe."""
    if not isinstance(recipe, DockerArchiveRecipe):
        raise TypeError("Docker load commands require a DockerArchiveRecipe")
    return ("docker", "load", "--input", str(recipe.archive))


def loaded_archive_references(output: str) -> tuple[str, ...]:
    """Return the references `docker load` reports, in the order it printed them.

    `docker load` names each loaded image on stdout as `Loaded image: <ref>`, or
    `Loaded image ID: sha256:<digest>` for an untagged image. Both forms are valid
    retag sources, so both are returned.
    """
    references: list[str] = []
    for line in output.splitlines():
        candidate = line.strip()
        if candidate.startswith(_LOADED_IMAGE_PREFIX):
            reference = candidate.removeprefix(_LOADED_IMAGE_PREFIX).strip()
            if reference:
                references.append(canonical_image_reference(reference))
        elif candidate.startswith(_LOADED_IMAGE_ID_PREFIX):
            reference = candidate.removeprefix(_LOADED_IMAGE_ID_PREFIX).strip()
            if reference:
                references.append(reference)
    return tuple(references)


def _load_archive_image(recipe: DockerArchiveRecipe, image: str) -> bool:
    """Load one saved image archive and retag it as `image`; return True when reused.

    The archive is loaded under the target tag's lease. When the recipe names no
    source reference the archive must either already carry the target or carry
    exactly one image, so a multi-image archive never retags an arbitrary member.
    """
    if recipe.only_if_missing and _docker_image_exists(image):
        return True
    result = subprocess.run(
        docker_load_command(recipe),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    loaded = loaded_archive_references(result.stdout)
    source = recipe.source
    if source is None:
        if image in loaded:
            return False
        if len(loaded) != 1:
            raise ImageBuildError(
                f"{recipe.archive} loaded {len(loaded)} images and none of them is "
                f"{image}; name the archive reference to retag"
            )
        source = loaded[0]
    elif source not in loaded and not _docker_image_exists(source):
        raise ImageBuildError(f"{recipe.archive} does not contain {source}")
    if source != image:
        subprocess.run(["docker", "tag", source, image], check=True)
    return False


def vrnetlab_build_commands(recipe: VrnetlabBuildRecipe) -> tuple[tuple[str, ...], ...]:
    """Return the make/build commands for a vrnetlab recipe.

    The build itself runs `make` in the recipe's builder directory (which owns the
    Makefile and stages the source), then retags the native vrnetlab image to the
    requested tag. Executor-callable for tests that need to inspect the command list.
    """
    if not isinstance(recipe, VrnetlabBuildRecipe):
        raise TypeError("vrnetlab build commands require a VrnetlabBuildRecipe")
    return (("make",),)


def _vrnetlab_native_image_tag(builder: Path) -> str | None:
    """Read the native tag a vrnetlab builder Makefile would produce.

    Mirrors engulf_clab_vrnetlab_build.images._native_image_tag_from_make so the
    core builder stays independent of the clab vrnetlab plugin: it evaluates the
    Makefile's `$(REGISTRY)vr-$(VR_NAME):$(VERSION)` form without depending on the
    plugin package.
    """
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


def _docker_image_exists(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _docker_remove_tag(image: str, *, check: bool) -> None:
    subprocess.run(
        ["docker", "image", "rm", image],
        check=check,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _build_vrnetlab_image(recipe: VrnetlabBuildRecipe) -> None:
    """Ensure a vrnetlab image exists, building it only when the tag is absent.

    vrnetlab source staging and rebuild-or-reuse decisions are owned by the vrnetlab
    provider/discovery stage (it extracts the qcow2, copies it into the builder, runs
    the fingerprinted make, and records the fingerprint). This executor is the idempotent
    finisher that the resolver's build loop drives: if the target tag already exists we
    are done — treating the recipe as satisfied rather than clobbering or pulling. When
    the tag is absent (e.g. image-build ran without a prior build), it stages nothing but
    runs `make` in the builder to let the Makefile produce the native image, then retags
    it to the requested tag, protecting and restoring any pre-existing target tag on
    failure so a bad rebuild does not clobber a previously-good image.
    """
    if _docker_image_exists(recipe.image):
        return
    if shutil.which("make") is None:
        raise ImageBuildError("missing required command: make")
    if not recipe.builder.is_dir():
        raise ImageBuildError(
            f"vrnetlab builder directory does not exist: {recipe.builder}"
        )

    subprocess.run(["make"], cwd=recipe.builder, check=True)
    if not _docker_image_exists(recipe.image):
        native = _vrnetlab_native_image_tag(recipe.builder)
        if native is None or not _docker_image_exists(native):
            raise ImageBuildError(
                "vrnetlab builder completed without creating required image "
                f"{recipe.image}"
            )
        subprocess.run(["docker", "tag", native, recipe.image], check=True)


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
    reused: set[str] = set()
    failed: dict[str, str] = {}
    direct_failures: list[ImageBuildFailure] = []
    lease_images = set(builds)
    lease_images.update(
        item.provision.recipe.source
        for item in builds.values()
        if item.provision is not None and isinstance(item.provision.recipe, DockerPullRecipe)
    )
    lease_images.update(
        item.provision.recipe.source
        for item in builds.values()
        if item.provision is not None
        and isinstance(item.provision.recipe, DockerArchiveRecipe)
        and item.provision.recipe.source is not None
    )
    builder_leases = {
        f"vrnetlab-builder:{item.provision.recipe.builder.resolve()}"
        for item in builds.values()
        if item.provision is not None
        and isinstance(item.provision.recipe, VrnetlabBuildRecipe)
    }
    leases = tuple(
        sorted(
            [f"docker-image:{image}" for image in sorted(lease_images)]
            + sorted(builder_leases)
        )
    )
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
                elif isinstance(recipe, VrnetlabBuildRecipe):
                    api.logger.info(
                        "building %s with vrnetlab builder %s", image, recipe.builder
                    )
                elif isinstance(recipe, DockerArchiveRecipe):
                    if recipe.only_if_missing:
                        api.logger.info(
                            "using local %s when present, otherwise loading it from %s",
                            image,
                            recipe.archive,
                        )
                    else:
                        api.logger.info("loading %s from %s", image, recipe.archive)
                elif isinstance(recipe, DockerPullRecipe):
                    if recipe.only_if_missing:
                        api.logger.info(
                            "using local %s when present, otherwise pulling it",
                            image,
                        )
                    else:
                        api.logger.info("pulling %s from %s", image, recipe.source)
                else:
                    api.logger.info("provisioning %s with %s recipe", image, recipe.recipe_kind)
            results = _build_batch(tuple(builds[image] for image in ready), max_workers)
            for item, error, used_local in results:
                image = item.image
                if error is None:
                    succeeded.add(image)
                    if used_local:
                        reused.add(image)
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
            if not _is_pull(builds[image])
            and not _is_archive(builds[image])
            and image not in reused
        )
    )
    pulled = tuple(
        sorted(
            image
            for image in succeeded
            if _is_pull(builds[image]) and image not in reused
        )
    )
    loaded = tuple(
        sorted(
            image
            for image in succeeded
            if _is_archive(builds[image]) and image not in reused
        )
    )
    return ImageBuildOutcome(
        graph, built, external, pulled, tuple(sorted(reused)), loaded
    )


def _build_batch(
    images: tuple[ResolvedImage, ...], max_workers: int
) -> tuple[tuple[ResolvedImage, str | None, bool], ...]:
    with ThreadPoolExecutor(max_workers=min(max_workers, len(images))) as executor:
        futures: tuple[tuple[ResolvedImage, Future[bool]], ...] = tuple(
            (image, executor.submit(_build_image, image)) for image in images
        )
        results: list[tuple[ResolvedImage, str | None, bool]] = []
        for image, future in futures:
            try:
                used_local = future.result()
            except ImageBuildError as error:
                results.append((image, str(error), False))
            else:
                results.append((image, None, used_local))
        return tuple(results)


# Serializes vrnetlab builds that share a builder directory: a vrnetlab Makefile
# owns that directory while it runs, so concurrent `make` in one builder corrupts the
# build. Keyed by the resolved builder path; cross-process safety additionally comes
# from the `vrnetlab-builder:` lease held in build_resolved_graph.
_VRNETLAB_LOCKS: dict[Path, threading.Lock] = {}
_VRNETLAB_LOCKS_GUARD = threading.Lock()


def _vrnetlab_lock(builder: Path) -> threading.Lock:
    key = builder.resolve()
    with _VRNETLAB_LOCKS_GUARD:
        return _VRNETLAB_LOCKS.setdefault(key, threading.Lock())


def _build_image(image: ResolvedImage) -> bool:
    if image.provision is None:
        raise ImageBuildError("external images cannot be provisioned directly")
    recipe = image.provision.recipe
    if isinstance(recipe, VrnetlabBuildRecipe):
        try:
            with _vrnetlab_lock(recipe.builder):
                _build_vrnetlab_image(recipe)
        except ImageBuildError:
            raise
        except (subprocess.CalledProcessError, OSError) as error:
            reason = (
                f"exit code {error.returncode}"
                if isinstance(error, subprocess.CalledProcessError)
                else str(error)
            )
            raise ImageBuildError(reason) from error
        return False
    try:
        if isinstance(recipe, DockerArchiveRecipe):
            return _load_archive_image(recipe, image.image)
        if isinstance(recipe, DockerfileRecipe):
            commands: tuple[tuple[str, ...], ...] = (docker_build_command(image),)
        elif isinstance(recipe, DockerPullRecipe):
            if recipe.only_if_missing and _docker_image_exists(image.image):
                return True
            commands = docker_pull_commands(image)
        else:
            # The recipe protocol is open; this executor only understands the
            # built-in recipe kinds.
            raise ImageBuildError(
                f"no executor for recipe kind {recipe.recipe_kind!r} for {image.image}"
            )
        for command in commands:
            subprocess.run(command, check=True)
        return False
    except subprocess.CalledProcessError as error:
        raise ImageBuildError(f"exit code {error.returncode}") from error
    except OSError as error:
        raise ImageBuildError(str(error)) from error


def _validate_recipe(image: ResolvedImage) -> None:
    assert image.provision is not None
    recipe = image.provision.recipe
    if isinstance(recipe, DockerPullRecipe):
        return
    if isinstance(recipe, DockerArchiveRecipe):
        if not recipe.archive.is_file():
            raise ImageBuildError(
                f"Docker image archive does not exist for {image.image}: {recipe.archive}"
            )
        return
    if isinstance(recipe, VrnetlabBuildRecipe):
        if not recipe.builder.is_dir():
            raise ImageBuildError(
                f"vrnetlab builder directory does not exist for {image.image}: "
                f"{recipe.builder}"
            )
        if not (recipe.builder / "Makefile").is_file():
            raise ImageBuildError(
                f"vrnetlab builder has no Makefile for {image.image}: {recipe.builder}"
            )
        if not recipe.source.exists():
            raise ImageBuildError(
                f"vrnetlab source does not exist for {image.image}: {recipe.source}"
            )
        return
    if not isinstance(recipe, DockerfileRecipe):
        # The recipe protocol is open; this executor only understands the built-in
        # recipe kinds, so an unrecognized recipe is a clear failure, not a silent skip.
        raise ImageBuildError(
            f"no executor for recipe kind {recipe.recipe_kind!r} for {image.image}"
        )
    if not recipe.dockerfile.is_file():
        raise ImageBuildError(f"Dockerfile does not exist for {image.image}: {recipe.dockerfile}")
    if not recipe.context.is_dir():
        raise ImageBuildError(
            f"Docker build context does not exist for {image.image}: {recipe.context}"
        )
    _validate_extra_args(recipe)


def _is_archive(image: ResolvedImage) -> bool:
    return image.provision is not None and isinstance(
        image.provision.recipe, DockerArchiveRecipe
    )


def _is_pull(image: ResolvedImage) -> bool:
    return image.provision is not None and isinstance(
        image.provision.recipe, DockerPullRecipe
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
