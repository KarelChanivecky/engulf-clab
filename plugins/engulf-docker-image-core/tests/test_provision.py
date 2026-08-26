from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
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
    VrnetlabBuildRecipe,
)

from engulf_docker_image_core import ImageResolutionError, provision_image_graph


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


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

    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/make")
    def test_vrnetlab_provider_is_preferred_over_pull_fallback(
        self, _which: Mock, run: Mock
    ) -> None:
        """Regression: a vrnetlab tag with no registry must resolve to the vrnetlab
        provider's build offer, not the pull-only fallback that previously failed."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(_rmtree, root)
        builder = root / "vendor" / "router"
        builder.mkdir(parents=True)
        (builder / "Makefile").write_text("all:\n", encoding="utf-8")
        source = root / "router.qcow2"
        source.write_bytes(b"qcow2")
        reference = "vrnetlab/vr-fortios:fgt_vm64_kvm-v8-build0235"

        class VrnetlabProvider:
            def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
                if not requirement.canonical_reference.startswith("vrnetlab/"):
                    return None
                return ImageProviderResponse.offer(
                    ImageProvision(
                        requirement.canonical_reference,
                        VrnetlabBuildRecipe(
                            source=source, builder=builder, image=requirement.canonical_reference
                        ),
                        origin="vrnetlab node fortios",
                    ),
                    authority=ProvisionAuthority.PREFERRED,
                    fallback_on_failure=True,
                )

        def inspect(command: tuple[str, ...], **_: object) -> Mock:
            result = Mock()
            result.returncode = 0
            result.stdout = "sha256:exists\n"
            return result

        run.side_effect = inspect
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()

        outcome = provision_image_graph(
            ImageBuildGraph((ImageRequirement(reference),)),
            api=api,
            providers=(
                RegisteredImageProvider("org.engulf.docker.vrnetlab-build", VrnetlabProvider()),
            ),
        )

        self.assertEqual(outcome.built, (reference,))
        self.assertEqual(outcome.pulled, ())
        # Only the existence check ran — no `docker pull` and no `make`.
        self.assertEqual(len(run.call_args_list), 1)
        self.assertEqual(
            list(run.call_args_list[0].args[0][:3]), ["docker", "image", "inspect"]
        )


if __name__ == "__main__":
    unittest.main()
