from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_docker_image_api import DockerfileRecipe

from engulf_docker_image_core import dockerfile_requirements
from engulf_docker_image_core.errors import DockerfileAnalysisError


class DockerfileTest(unittest.TestCase):
    def test_discovers_args_and_ignores_stage_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / "Dockerfile"
            dockerfile.write_text(
                "ARG BASE=example/base\n"
                "FROM ${BASE} AS build\n"
                "FROM build AS copied\n"
                "FROM example/runtime:1\n",
                encoding="utf-8",
            )
            requirements = dockerfile_requirements(DockerfileRecipe(dockerfile, root))
        self.assertEqual(
            tuple(item.reference for item in requirements),
            ("example/base", "example/runtime:1"),
        )

    def test_unresolved_dynamic_from_is_not_delegated_to_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / "Dockerfile"
            dockerfile.write_text("ARG BASE\nFROM ${BASE}\n", encoding="utf-8")

            with self.assertRaisesRegex(DockerfileAnalysisError, "dynamic FROM"):
                dockerfile_requirements(DockerfileRecipe(dockerfile, root))


if __name__ == "__main__":
    unittest.main()
