from __future__ import annotations

import subprocess
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI
from engulf_docker_image_api import (
    DockerPullRecipe,
    ImageBuildGraph,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    RegisteredImageProvider,
)

from engulf_docker_image_core import ImageResolutionError, provision_image_graph


class _MirrorProvider:
    def __init__(self) -> None:
        self.calls = 0

    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse:
        self.calls += 1
        return ImageProviderResponse.offer(
            ImageProvision(
                requirement.canonical_reference,
                DockerPullRecipe(f"mirror.local/{requirement.canonical_reference}"),
            ),
            authority=ProvisionAuthority.PREFERRED,
        )


class ProvisionTest(unittest.TestCase):
    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker")
    def test_default_pull_provisions_an_unclaimed_root(self, _which: Mock, run: Mock) -> None:
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()

        outcome = provision_image_graph(
            ImageBuildGraph((ImageRequirement("example/app:1"),)),
            api=api,
        )

        self.assertEqual(outcome.external, ())
        self.assertEqual(outcome.pulled, ("example/app:1",))
        run.assert_called_once_with(("docker", "pull", "example/app:1"), check=True)

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker")
    def test_failed_mirror_falls_back_without_reprobing_provider(
        self, _which: Mock, run: Mock
    ) -> None:
        mirror = _MirrorProvider()
        run.side_effect = (
            subprocess.CalledProcessError(1, ("docker", "pull")),
            None,
        )
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()

        outcome = provision_image_graph(
            ImageBuildGraph((ImageRequirement("example/app:1"),)),
            api=api,
            providers=(RegisteredImageProvider("org.example.mirror", mirror),),
        )

        self.assertEqual(outcome.pulled, ("example/app:1",))
        self.assertEqual(mirror.calls, 1)
        self.assertEqual(
            tuple(call.args[0] for call in run.call_args_list),
            (
                ("docker", "pull", "mirror.local/example/app:1"),
                ("docker", "pull", "example/app:1"),
            ),
        )

    @patch("engulf_docker_image_core.build.subprocess.run")
    def test_terminal_rejection_prevents_public_pull(self, run: Mock) -> None:
        class Owner:
            def provide(self, requirement: ImageRequirement) -> ImageProviderResponse:
                del requirement
                return ImageProviderResponse.reject("unsupported owned tag")

        api = Mock(spec=InvocationAPI)
        with self.assertRaisesRegex(ImageResolutionError, "unsupported owned tag"):
            provision_image_graph(
                ImageBuildGraph((ImageRequirement("example/app:1"),)),
                api=api,
                providers=(RegisteredImageProvider("org.example.owner", Owner()),),
            )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
