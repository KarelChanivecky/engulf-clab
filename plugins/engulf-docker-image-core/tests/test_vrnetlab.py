from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI
from engulf_docker_image_api import (
    DockerPullRecipe,
    ImageProvision,
    ImageRequirement,
    VrnetlabBuildRecipe,
)

from engulf_docker_image_core import (
    ImageBuildError,
    ResolvedImage,
    ResolvedImageGraph,
    build_resolved_graph,
    vrnetlab_build_commands,
)


def _vrnetlab_image(tag: str, builder: Path, source: Path) -> ResolvedImage:
    provision = ImageProvision(
        tag,
        VrnetlabBuildRecipe(source=source, builder=builder, image=tag),
        origin="test vrnetlab",
    )
    return ResolvedImage(tag, ImageRequirement(tag), provision, "org.engulf.docker.vrnetlab-build", ())


class VrnetlabExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        self.builder = self.root / "vendor" / "router"
        self.builder.mkdir(parents=True)
        (self.builder / "Makefile").write_text("all: ; @echo built\n", encoding="utf-8")
        self.source = self.root / "images" / "router.qcow2"
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_bytes(b"qcow2")
        self.tag = "vrnetlab/vr-router:1.0.0"
        self.api = Mock(spec=InvocationAPI)
        self.api.leases.return_value = nullcontext()

    def _graph(self, tag: str) -> ResolvedImageGraph:
        return ResolvedImageGraph((tag,), (_vrnetlab_image(tag, self.builder, self.source),))

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/make")
    def test_graph_builds_vrnetlab_recipe_with_make(self, _which: Mock, run: Mock) -> None:
        # The make run itself creates the requested tag: first inspect says absent,
        # the post-make inspect says present, so no retag is needed.
        inspected: list[str] = []

        def inspect(command: list[str], **_: object) -> Mock:
            result = Mock()
            result.returncode = 0
            if command[:3] == ["docker", "image", "inspect"]:
                inspected.append(command[5])
                result.stdout = f"sha256:{len(inspected)}\n" if len(inspected) > 1 else ""
                result.returncode = 1 if len(inspected) == 1 else 0
            return result

        run.side_effect = inspect

        outcome = build_resolved_graph(self._graph(self.tag), api=self.api)

        make_calls = [call for call in run.call_args_list if call.args[0] == ["make"]]
        self.assertEqual(len(make_calls), 1)
        self.assertEqual(make_calls[0].kwargs["cwd"], self.builder)
        self.assertEqual(outcome.built, (self.tag,))
        self.assertEqual(outcome.pulled, ())
        self.assertEqual(outcome.external, ())

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/make")
    def test_graph_retags_native_vrnetlab_image(self, _which: Mock, run: Mock) -> None:
        native = "vrnetlab/vr-router-native:1.0.0"

        def inspect(command: list[str], **_: object) -> Mock:
            result = Mock()
            result.returncode = 1
            result.stdout = ""
            if command[:3] == ["docker", "image", "inspect"] and command[5] == native:
                result.returncode = 0
                result.stdout = "sha256:native\n"
            return result

        run.side_effect = inspect
        with patch(
            "engulf_docker_image_core.build._vrnetlab_native_image_tag",
            return_value=native,
        ):
            outcome = build_resolved_graph(self._graph(self.tag), api=self.api)

        tag_calls = [call for call in run.call_args_list if call.args[0][:2] == ["docker", "tag"]]
        self.assertEqual(len(tag_calls), 1)
        self.assertEqual(tag_calls[0].args[0], ["docker", "tag", native, self.tag])
        self.assertEqual(outcome.built, (self.tag,))

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/make")
    def test_existing_requested_tag_skips_the_build(self, _which: Mock, run: Mock) -> None:
        def inspect(command: list[str], **_: object) -> Mock:
            result = Mock()
            result.returncode = 0
            result.stdout = "sha256:exists\n"
            return result

        run.side_effect = inspect

        outcome = build_resolved_graph(self._graph(self.tag), api=self.api)

        self.assertFalse(any(call.args[0] == ["make"] for call in run.call_args_list))
        self.assertEqual(outcome.built, (self.tag,))

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/make")
    def test_make_failure_reports_exit_code(self, _which: Mock, run: Mock) -> None:
        import subprocess

        def run_side_effect(command: list[str], **kwargs: object) -> Mock:
            result = Mock()
            result.returncode = 0
            result.stdout = ""
            if command == ["make"]:
                result.returncode = 2
                if kwargs.get("check"):
                    raise subprocess.CalledProcessError(2, command)
            return result

        run.side_effect = run_side_effect

        with self.assertRaisesRegex(ImageBuildError, "exit code 2"):
            build_resolved_graph(self._graph(self.tag), api=self.api)

    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/make")
    def test_builder_directory_holds_a_lease(self, _which: Mock) -> None:
        def inspect(command: list[str], **_: object) -> Mock:
            result = Mock()
            result.returncode = 0
            result.stdout = "sha256:exists\n"
            return result

        with patch("engulf_docker_image_core.build.subprocess.run", side_effect=inspect):
            build_resolved_graph(self._graph(self.tag), api=self.api)

        self.api.leases.assert_called_once_with(
            (
                f"docker-image:{self.tag}",
                f"vrnetlab-builder:{self.builder.resolve()}",
            )
        )


class VrnetlabValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        self.builder = self.root / "vendor" / "router"
        self.builder.mkdir(parents=True)
        (self.builder / "Makefile").write_text("all:\n", encoding="utf-8")
        self.source = self.root / "router.qcow2"
        self.source.write_bytes(b"qcow2")

    def _image(self, builder: Path, source: Path) -> ResolvedImage:
        provision = ImageProvision(
            "vrnetlab/vr-router:1.0.0",
            VrnetlabBuildRecipe(source=source, builder=builder, image="vrnetlab/vr-router"),
        )
        return ResolvedImage(
            "vrnetlab/vr-router:1.0.0", ImageRequirement("vrnetlab/vr-router"), provision, "p", ()
        )

    def test_valid_recipe_passes_validation(self) -> None:
        from engulf_docker_image_core.build import _validate_recipe

        _validate_recipe(self._image(self.builder, self.source))

    def test_missing_builder_directory_fails(self) -> None:
        from engulf_docker_image_core.build import _validate_recipe

        with self.assertRaisesRegex(ImageBuildError, "builder directory does not exist"):
            _validate_recipe(self._image(self.builder / "nope", self.source))

    def test_missing_makefile_fails(self) -> None:
        from engulf_docker_image_core.build import _validate_recipe

        empty = self.builder.parent / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(ImageBuildError, "no Makefile"):
            _validate_recipe(self._image(empty, self.source))

    def test_missing_source_fails(self) -> None:
        from engulf_docker_image_core.build import _validate_recipe

        with self.assertRaisesRegex(ImageBuildError, "source does not exist"):
            _validate_recipe(self._image(self.builder, self.root / "absent.qcow2"))


class VrnetlabClassificationTest(unittest.TestCase):
    def test_vrnetlab_outcome_counts_as_built_not_pulled(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        root = Path(self._directory.name).resolve()
        builder = root / "vendor" / "router"
        builder.mkdir(parents=True)
        (builder / "Makefile").write_text("all:\n", encoding="utf-8")
        source = root / "router.qcow2"
        source.write_bytes(b"qcow2")
        tag = "vrnetlab/vr-router:1.0.0"
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()

        def inspect(command: list[str], **_: object) -> Mock:
            result = Mock()
            result.returncode = 0
            result.stdout = "sha256:exists\n"
            return result

        with (
            patch("engulf_docker_image_core.build.subprocess.run", side_effect=inspect),
            patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/make"),
        ):
            outcome = build_resolved_graph(
                ResolvedImageGraph((tag,), (_vrnetlab_image(tag, builder, source),)), api=api
            )

        self.assertEqual(outcome.built, (tag,))
        self.assertEqual(outcome.pulled, ())

    def test_pull_and_vrnetlab_images_classify_separately(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        root = Path(self._directory.name).resolve()
        builder = root / "vendor" / "router"
        builder.mkdir(parents=True)
        (builder / "Makefile").write_text("all:\n", encoding="utf-8")
        source = root / "router.qcow2"
        source.write_bytes(b"qcow2")
        vr_tag = "vrnetlab/vr-router:1.0.0"
        pull_tag = "example/pulled:latest"
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()
        pulled = ResolvedImage(
            pull_tag,
            ImageRequirement(pull_tag),
            ImageProvision(pull_tag, DockerPullRecipe("example/pulled")),
            "org.engulf.docker.pull",
            (),
        )

        def run(command: list[str], **_: object) -> Mock:
            result = Mock()
            result.returncode = 0
            result.stdout = "sha256:x\n" if command[:3] == ["docker", "image", "inspect"] else ""
            return result

        with (
            patch("engulf_docker_image_core.build.subprocess.run", side_effect=run),
            patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker"),
        ):
            outcome = build_resolved_graph(
                ResolvedImageGraph(
                    (pull_tag, vr_tag), (pulled, _vrnetlab_image(vr_tag, builder, source))
                ),
                api=api,
            )

        self.assertEqual(outcome.built, (vr_tag,))
        self.assertEqual(outcome.pulled, (pull_tag,))


class VrnetlabCommandsTest(unittest.TestCase):
    def test_vrnetlab_build_commands_return_make(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            recipe = VrnetlabBuildRecipe(root / "a.qcow2", root / "builder", "vrnetlab/vr:1")

            self.assertEqual(vrnetlab_build_commands(recipe), (("make",),))

    def test_non_vrnetlab_recipes_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            vrnetlab_build_commands(
                DockerPullRecipe("example/root")  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
