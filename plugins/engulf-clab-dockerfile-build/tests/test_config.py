from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_dockerfile_build.config import build_requests_from_topology, docker_build_jobs
from engulf_clab_dockerfile_build.errors import DockerfileError


class ConfigurationTest(unittest.TestCase):
    def test_runtime_build_job_limit(self) -> None:
        self.assertEqual(docker_build_jobs("eclab", {}), 2)
        self.assertEqual(docker_build_jobs("fclab", {"FCLAB_DOCKER_BUILD_JOBS": "4"}), 4)
        with self.assertRaisesRegex(DockerfileError, "positive integer"):
            docker_build_jobs("eclab", {"ECLAB_DOCKER_BUILD_JOBS": "0"})

    def test_build_request_uses_node_image_and_relative_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            node_dir = root / "api"
            node_dir.mkdir()
            (node_dir / "Dockerfile").touch()
            data = {
                "topology": {
                    "nodes": {
                        "api": {
                            "image": "example/api:dev",
                            "env": {
                                "ENGULF_CLAB_DOCKERFILE": "api/Dockerfile",
                                "ENGULF_CLAB_DOCKER_CTX": "api",
                                "ENGULF_CLAB_DOCKER_VAR_VERSION": "1.2.3",
                                "ENGULF_CLAB_DOCKER_ARGS": "--pull --label 'team=netops'",
                            },
                        }
                    }
                }
            }
            requests = build_requests_from_topology(
                root / "lab.clab.yml", data, application_name="engulf-clab"
            )

        self.assertEqual(requests[0].image, "example/api:dev")
        self.assertEqual(requests[0].dockerfile, node_dir / "Dockerfile")
        self.assertEqual(requests[0].context, node_dir)
        self.assertEqual(requests[0].build_args, (("VERSION", "1.2.3"),))
        self.assertEqual(requests[0].extra_args, ("--pull", "--label", "team=netops"))

    def test_missing_context_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / "Dockerfile"
            dockerfile.touch()
            data = {
                "topology": {
                    "nodes": {
                        "api": {"image": "example/api", "env": {"ENGULF_CLAB_DOCKERFILE": "Dockerfile"}}
                    }
                }
            }
            with self.assertRaisesRegex(DockerfileError, "DOCKER_CTX"):
                build_requests_from_topology(root / "lab.clab.yml", data, application_name="engulf-clab")

    def test_edition_name_changes_prefix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").touch()
            data = {
                "topology": {
                    "nodes": {
                        "api": {
                            "image": "example/api",
                            "env": {
                                "ACME_CLAB_DOCKERFILE": "Dockerfile",
                                "ACME_CLAB_DOCKER_CTX": ".",
                            },
                        }
                    }
                }
            }
            requests = build_requests_from_topology(root / "lab.clab.yml", data, application_name="acme-clab")

        self.assertEqual(len(requests), 1)
