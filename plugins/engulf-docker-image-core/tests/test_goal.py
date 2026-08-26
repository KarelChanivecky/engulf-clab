from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import GoalAPI, GoalResultStatus, Invocation
from engulf_docker_image_api import ImageBuildGraph, ImageRequirement

from engulf_docker_image_core import DockerImageGoal


class GoalTest(unittest.TestCase):
    @patch("engulf_docker_image_core.build.subprocess.run")
    @patch("engulf_docker_image_core.build.shutil.which", return_value="/usr/bin/docker")
    def test_injected_non_yaml_loader_can_construct_graph(
        self, _which: Mock, _run: Mock
    ) -> None:
        seen: list[tuple[str, ...]] = []

        def load(invocation: Invocation) -> ImageBuildGraph:
            seen.append(invocation.arguments)
            return ImageBuildGraph((ImageRequirement("registry.example/base:1"),))

        api = Mock(spec=GoalAPI)
        api.dispatch.return_value = ()
        api.leases.return_value = nullcontext()
        result = DockerImageGoal(load).achieve(
            Invocation(("values.env",), Path("/work"), {}),
            api,
        )

        self.assertEqual(result.status, GoalResultStatus.COMPLETED)
        assert result.value is not None
        self.assertEqual(result.value.external, ())
        self.assertEqual(result.value.pulled, ("registry.example/base:1",))
        self.assertEqual(seen, [("values.env",)])


if __name__ == "__main__":
    unittest.main()
