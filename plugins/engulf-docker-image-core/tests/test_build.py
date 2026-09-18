from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI
from engulf_docker_image_api import (
    DockerfileRecipe,
    DockerPullRecipe,
    ImageProvision,
    ImageRequirement,
)

from engulf_docker_image_core import (
    ImageBuildError,
    ResolvedImage,
    ResolvedImageGraph,
    build_resolved_graph,
    docker_build_command,
)


class BuildTest(unittest.TestCase):
    def test_authenticates_before_dispatch_and_elevates_only_docker(self) -> None:
        image = ResolvedImage(
            "example/app:latest",
            ImageRequirement("example/app"),
            ImageProvision("example/app", DockerPullRecipe("example/app")),
            "org.example.provider",
            (),
        )
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()
        events: list[object] = []
        with (
            patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker"),
            patch("engulf_docker_image_core.build.docker_needs_sudo", return_value=True),
            patch("engulf_docker_image_core.build.require_root_access", side_effect=lambda: events.append("auth")),
            patch("engulf_docker_image_core.build.docker_command", side_effect=lambda argv: ["sudo", "--", *argv]),
            patch("engulf_docker_image_core.build.subprocess.run", side_effect=lambda argv, **_kwargs: events.append(argv)),
        ):
            outcome = build_resolved_graph(ResolvedImageGraph((image.image,), (image,)), api=api)
        self.assertEqual(events, ["auth", ["sudo", "--", "docker", "pull", "example/app:latest"]])
        self.assertEqual(outcome.pulled, (image.image,))

    def test_build_recipe_cannot_bypass_graph_with_pull(self) -> None:
        provision = ImageProvision(
            "example/app",
            DockerfileRecipe(
                Path("/tmp/Dockerfile"), Path("/tmp"), extra_args=("--pull",)
            ),
        )
        image = ResolvedImage(
            "example/app:latest",
            ImageRequirement("example/app"),
            provision,
            "org.example.provider",
            (),
        )

        with self.assertRaisesRegex(ImageBuildError, "image graph"):
            docker_build_command(image)

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker")
    def test_builds_dependencies_before_consumers(self, _which: Mock, run: Mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / "Dockerfile"
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            recipe = DockerfileRecipe(dockerfile, root)
            base = ResolvedImage(
                "example/base:latest",
                ImageRequirement("example/base"),
                ImageProvision("example/base", recipe),
                "org.example.provider",
                (),
            )
            app = ResolvedImage(
                "example/app:latest",
                ImageRequirement("example/app"),
                ImageProvision("example/app", recipe),
                "org.example.provider",
                ("example/base:latest",),
            )
            api = Mock(spec=InvocationAPI)
            api.leases.return_value = nullcontext()
            outcome = build_resolved_graph(ResolvedImageGraph((app.image,), (app, base)), api=api)

        self.assertEqual(outcome.built, ("example/app:latest", "example/base:latest"))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][4:6], ("--tag", "example/base:latest"))
        self.assertEqual(run.call_args_list[1].args[0][4:6], ("--tag", "example/app:latest"))
        api.leases.assert_called_once_with(
            ("docker-image:example/app:latest", "docker-image:example/base:latest")
        )

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker")
    def test_pull_recipe_retags_a_mirror_source(self, _which: Mock, run: Mock) -> None:
        provision = ImageProvision(
            "example/app",
            DockerPullRecipe("mirror.local/example/app"),
        )
        image = ResolvedImage(
            "example/app:latest",
            ImageRequirement("example/app"),
            provision,
            "org.example.mirror",
            (),
        )
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()

        outcome = build_resolved_graph(ResolvedImageGraph((image.image,), (image,)), api=api)

        self.assertEqual(outcome.pulled, ("example/app:latest",))
        self.assertEqual(outcome.built, ())
        self.assertEqual(
            tuple(call.args[0] for call in run.call_args_list),
            (
                ("docker", "pull", "mirror.local/example/app:latest"),
                (
                    "docker",
                    "tag",
                    "mirror.local/example/app:latest",
                    "example/app:latest",
                ),
            ),
        )
        api.leases.assert_called_once_with(
            (
                "docker-image:example/app:latest",
                "docker-image:mirror.local/example/app:latest",
            )
        )


if __name__ == "__main__":
    unittest.main()
