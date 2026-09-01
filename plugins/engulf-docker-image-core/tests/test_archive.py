from __future__ import annotations

import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI
from engulf_docker_image_api import (
    DockerArchiveRecipe,
    DockerPullRecipe,
    ImageProvision,
    ImageRequirement,
)

from engulf_docker_image_core import (
    ImageBuildError,
    ResolvedImage,
    ResolvedImageGraph,
    build_resolved_graph,
    docker_load_command,
    loaded_archive_references,
)


def _archive_image(
    tag: str,
    archive: Path,
    *,
    source: str | None = None,
    only_if_missing: bool = False,
) -> ResolvedImage:
    provision = ImageProvision(
        tag,
        DockerArchiveRecipe(archive, source, only_if_missing),
        origin="test archive",
    )
    return ResolvedImage(
        tag, ImageRequirement(tag), provision, "org.engulf.docker.image-archive", ()
    )


class DockerRunStub:
    """Answer `docker image inspect`, `docker load`, and `docker tag` in one stub."""

    def __init__(self, *, existing: Sequence[str] = (), loaded: Sequence[str] = ()) -> None:
        self.existing = set(existing)
        self.loaded = tuple(loaded)
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = tuple(command)
        self.commands.append(argv)
        if argv[:3] == ("docker", "image", "inspect"):
            present = argv[-1] in self.existing
            return subprocess.CompletedProcess(argv, 0 if present else 1, "sha256:id" if present else "")
        if argv[:2] == ("docker", "load"):
            output = "".join(f"Loaded image: {reference}\n" for reference in self.loaded)
            self.existing.update(self.loaded)
            return subprocess.CompletedProcess(argv, 0, output)
        if argv[:2] == ("docker", "pull"):
            self.existing.add(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "")
        if argv[:2] == ("docker", "tag"):
            self.existing.add(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "")
        raise AssertionError(f"unexpected command: {argv}")


class LoadedReferencesTest(unittest.TestCase):
    def test_tagged_and_untagged_lines_are_both_retag_sources(self) -> None:
        output = (
            "Loaded image: example/router:1.0.0\n"
            "Loaded image ID: sha256:0123456789ab\n"
            "unrelated progress line\n"
        )

        self.assertEqual(
            loaded_archive_references(output),
            ("example/router:1.0.0", "sha256:0123456789ab"),
        )

    def test_bare_repository_gains_the_implicit_latest_tag(self) -> None:
        self.assertEqual(
            loaded_archive_references("Loaded image: example/router\n"),
            ("example/router:latest",),
        )

    def test_load_command_names_the_archive(self) -> None:
        self.assertEqual(
            docker_load_command(DockerArchiveRecipe(Path("/labs/router.tar.gz"))),
            ("docker", "load", "--input", "/labs/router.tar.gz"),
        )


class ArchiveBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        self.archive = self.root / "router.tar.gz"
        self.archive.write_bytes(b"archive")
        self.tag = "example/router:1.0.0"

    def _api(self) -> Mock:
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()
        return api

    def _build(self, image: ResolvedImage, stub: DockerRunStub) -> tuple[object, Mock]:
        api = self._api()
        with (
            patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker"),
            patch("engulf_docker_image_core.build.subprocess.run", side_effect=stub),
        ):
            outcome = build_resolved_graph(
                ResolvedImageGraph((image.image,), (image,)), api=api
            )
        return outcome, api

    def test_archive_carrying_the_target_loads_without_retagging(self) -> None:
        stub = DockerRunStub(loaded=[self.tag])

        outcome, _api = self._build(_archive_image(self.tag, self.archive), stub)

        self.assertEqual(
            stub.commands, [("docker", "load", "--input", str(self.archive))]
        )
        self.assertEqual(outcome.loaded, (self.tag,))
        self.assertEqual(outcome.built, ())
        self.assertEqual(outcome.pulled, ())
        self.assertEqual(outcome.reused, ())

    def test_single_image_archive_is_retagged_as_the_target(self) -> None:
        stub = DockerRunStub(loaded=["vendor/router:2026.08"])

        outcome, _api = self._build(_archive_image(self.tag, self.archive), stub)

        self.assertEqual(
            stub.commands[-1], ("docker", "tag", "vendor/router:2026.08", self.tag)
        )
        self.assertEqual(outcome.loaded, (self.tag,))

    def test_selected_source_is_retagged_from_a_multi_image_archive(self) -> None:
        stub = DockerRunStub(loaded=["vendor/switch:1.0.0", "vendor/router:2026.08"])

        self._build(
            _archive_image(self.tag, self.archive, source="vendor/router:2026.08"), stub
        )

        self.assertEqual(
            stub.commands[-1], ("docker", "tag", "vendor/router:2026.08", self.tag)
        )

    def test_multi_image_archive_without_a_source_fails(self) -> None:
        stub = DockerRunStub(loaded=["vendor/switch:1.0.0", "vendor/router:2026.08"])

        with self.assertRaisesRegex(ImageBuildError, "loaded 2 images"):
            self._build(_archive_image(self.tag, self.archive), stub)

    def test_absent_selected_source_fails(self) -> None:
        stub = DockerRunStub(loaded=["vendor/switch:1.0.0"])

        with self.assertRaisesRegex(ImageBuildError, "does not contain"):
            self._build(
                _archive_image(self.tag, self.archive, source="vendor/router:2026.08"),
                stub,
            )

    def test_missing_only_recipe_reuses_an_existing_local_tag(self) -> None:
        stub = DockerRunStub(existing=[self.tag])

        outcome, _api = self._build(
            _archive_image(self.tag, self.archive, only_if_missing=True), stub
        )

        self.assertEqual(
            stub.commands,
            [("docker", "image", "inspect", "--format", "{{.Id}}", self.tag)],
        )
        self.assertEqual(outcome.reused, (self.tag,))
        self.assertEqual(outcome.loaded, ())
        self.assertEqual(outcome.built, ())

    def test_missing_only_recipe_loads_an_absent_tag(self) -> None:
        stub = DockerRunStub(loaded=[self.tag])

        outcome, _api = self._build(
            _archive_image(self.tag, self.archive, only_if_missing=True), stub
        )

        self.assertIn(("docker", "load", "--input", str(self.archive)), stub.commands)
        self.assertEqual(outcome.loaded, (self.tag,))
        self.assertEqual(outcome.reused, ())

    def test_leases_cover_the_target_and_the_selected_source(self) -> None:
        stub = DockerRunStub(loaded=["vendor/router:2026.08"])

        _outcome, api = self._build(
            _archive_image(self.tag, self.archive, source="vendor/router:2026.08"), stub
        )

        api.leases.assert_called_once_with(
            (
                "docker-image:example/router:1.0.0",
                "docker-image:vendor/router:2026.08",
            )
        )

    def test_missing_archive_fails_before_docker_runs(self) -> None:
        stub = DockerRunStub()
        image = _archive_image(self.tag, self.root / "absent.tar.gz")

        with self.assertRaisesRegex(ImageBuildError, "archive does not exist"):
            self._build(image, stub)
        self.assertEqual(stub.commands, [])

    def test_archive_and_pull_images_classify_separately(self) -> None:
        stub = DockerRunStub(loaded=[self.tag])
        pull_tag = "example/client:latest"
        pulled = ResolvedImage(
            pull_tag,
            ImageRequirement(pull_tag),
            ImageProvision(pull_tag, DockerPullRecipe(pull_tag)),
            "org.example.mirror",
            (),
        )
        api = self._api()
        with (
            patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker"),
            patch("engulf_docker_image_core.build.subprocess.run", side_effect=stub),
        ):
            outcome = build_resolved_graph(
                ResolvedImageGraph(
                    (self.tag, pull_tag),
                    (_archive_image(self.tag, self.archive), pulled),
                ),
                api=api,
            )

        self.assertEqual(outcome.loaded, (self.tag,))
        self.assertEqual(outcome.pulled, (pull_tag,))
        self.assertEqual(outcome.built, ())
