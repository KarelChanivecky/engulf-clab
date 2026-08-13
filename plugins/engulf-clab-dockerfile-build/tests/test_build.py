from __future__ import annotations

import subprocess
import unittest
from contextlib import nullcontext
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI

from engulf_clab_dockerfile_build.build import _command, build_images
from engulf_clab_dockerfile_build.config import BuildRequest
from engulf_clab_dockerfile_build.errors import DockerfileError


def request(node_name: str = "api", image: str = "example/api:dev") -> BuildRequest:
    return BuildRequest(
        node_name=node_name,
        image=image,
        dockerfile=Path("/lab/api/Dockerfile"),
        context=Path("/lab/api"),
        build_args=(("VERSION", "1.2.3"),),
        extra_args=("--pull",),
    )


class BuildTest(unittest.TestCase):
    def test_command_places_context_last(self) -> None:
        self.assertEqual(
            _command(request()),
            (
                "docker", "build", "--file", "/lab/api/Dockerfile", "--tag", "example/api:dev",
                "--build-arg", "VERSION=1.2.3", "--pull", "/lab/api",
            ),
        )

    @patch("engulf_clab_dockerfile_build.build.subprocess.run")
    @patch("engulf_clab_dockerfile_build.build.shutil.which", return_value="/usr/bin/docker")
    def test_identical_tag_definitions_build_once(self, _which: Mock, run: Mock) -> None:
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()
        build_images((request("api"), request("worker")), api=api)
        run.assert_called_once()
        api.leases.assert_called_once_with(("docker-image:example/api:dev",))

    @patch("engulf_clab_dockerfile_build.build.subprocess.run")
    @patch("engulf_clab_dockerfile_build.build.shutil.which", return_value="/usr/bin/docker")
    def test_distinct_tags_build_concurrently(self, _which: Mock, run: Mock) -> None:
        rendezvous = Barrier(2)
        run.side_effect = lambda *_args, **_kwargs: rendezvous.wait(timeout=2)
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()

        build_images(
            (request("api"), request("worker", "example/worker:dev")),
            api=api,
            max_workers=2,
        )

        self.assertEqual(run.call_count, 2)
        api.leases.assert_called_once_with(
            (
                "docker-image:example/api:dev",
                "docker-image:example/worker:dev",
            )
        )

    @patch("engulf_clab_dockerfile_build.build.subprocess.run")
    @patch("engulf_clab_dockerfile_build.build.shutil.which", return_value="/usr/bin/docker")
    def test_all_started_failures_are_reported(self, _which: Mock, run: Mock) -> None:
        run.side_effect = subprocess.CalledProcessError(7, ("docker", "build"))
        api = Mock(spec=InvocationAPI)
        api.leases.return_value = nullcontext()

        with self.assertRaisesRegex(DockerfileError, "example/api:dev.*example/worker:dev"):
            build_images(
                (request("api"), request("worker", "example/worker:dev")),
                api=api,
                max_workers=2,
            )

        self.assertEqual(run.call_count, 2)

    def test_conflicting_tag_definitions_fail(self) -> None:
        api = Mock(spec=InvocationAPI)
        conflicting = BuildRequest(
            node_name="worker",
            image="example/api:dev",
            dockerfile=Path("/lab/worker/Dockerfile"),
            context=Path("/lab/worker"),
            build_args=(),
            extra_args=(),
        )
        with self.assertRaisesRegex(DockerfileError, "conflicting"):
            build_images((request(), conflicting), api=api)
