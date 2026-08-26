from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_dockerfile_build.config import build_requests_from_topology
from engulf_clab_dockerfile_build.errors import DockerfileError


class ConfigurationTest(unittest.TestCase):
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
                                "ECLAB_DOCKERFILE": "api/Dockerfile",
                                "ECLAB_DOCKER_CTX": "api",
                                "ECLAB_DOCKER_VAR_VERSION": "1.2.3",
                                "ECLAB_DOCKER_ARGS": "--label 'team=netops'",
                            },
                        }
                    }
                }
            }
            requests = build_requests_from_topology(root / "lab.clab.yml", data)

        self.assertEqual(requests[0].image, "example/api:dev")
        self.assertEqual(requests[0].dockerfile, node_dir / "Dockerfile")
        self.assertEqual(requests[0].context, node_dir)
        self.assertEqual(requests[0].build_args, (("VERSION", "1.2.3"),))
        self.assertEqual(requests[0].extra_args, ("--label", "team=netops"))
        self.assertFalse(requests[0].base_node)

    def test_base_node_marker_is_parsed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").touch()
            data = {
                "topology": {
                    "nodes": {
                        "base": {
                            "image": "example/base",
                            "env": {
                                "ECLAB_DOCKERFILE": "Dockerfile",
                                "ECLAB_DOCKER_CTX": ".",
                                "ECLAB_DOCKER_BASE_NODE": "yes",
                            },
                        }
                    }
                }
            }

            requests = build_requests_from_topology(root / "lab.clab.yml", data)

        self.assertTrue(requests[0].base_node)

    def test_base_node_requires_a_dockerfile(self) -> None:
        data = {
            "topology": {
                "nodes": {
                    "base": {
                        "image": "example/base",
                        "env": {"ECLAB_DOCKER_BASE_NODE": "true"},
                    }
                }
            }
        }

        with self.assertRaisesRegex(DockerfileError, "BASE_NODE.*DOCKERFILE"):
            build_requests_from_topology(Path("/lab/lab.clab.yml"), data)

    def test_base_node_value_must_be_a_boolean_string(self) -> None:
        data = {
            "topology": {
                "nodes": {
                    "base": {
                        "image": "example/base",
                        "env": {"ECLAB_DOCKER_BASE_NODE": True},
                    }
                }
            }
        }

        with self.assertRaisesRegex(DockerfileError, "boolean string"):
            build_requests_from_topology(Path("/lab/lab.clab.yml"), data)

    def test_pull_argument_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").touch()
            data = {
                "topology": {
                    "nodes": {
                        "api": {
                            "image": "example/api",
                            "env": {
                                "ECLAB_DOCKERFILE": "Dockerfile",
                                "ECLAB_DOCKER_CTX": ".",
                                "ECLAB_DOCKER_ARGS": "--pull",
                            },
                        }
                    }
                }
            }
            with self.assertRaisesRegex(DockerfileError, "image graph"):
                build_requests_from_topology(root / "lab.clab.yml", data)

    def test_missing_context_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / "Dockerfile"
            dockerfile.touch()
            data = {
                "topology": {
                    "nodes": {
                        "api": {"image": "example/api", "env": {"ECLAB_DOCKERFILE": "Dockerfile"}}
                    }
                }
            }
            with self.assertRaisesRegex(DockerfileError, "DOCKER_CTX"):
                build_requests_from_topology(root / "lab.clab.yml", data)

    def test_variable_syntax_in_image_tag_is_rejected(self) -> None:
        variable_images = (
            "example/api:$TAG",
            "example/api:${TAG}",
            "example/api:${TAG:-dev}",
            "example/api:$$TAG",
        )
        for image in variable_images:
            with self.subTest(image=image):
                data = {
                    "topology": {
                        "nodes": {
                            "api": {
                                "image": image,
                                "env": {
                                    "ECLAB_DOCKERFILE": "Dockerfile",
                                    "ECLAB_DOCKER_CTX": ".",
                                },
                            }
                        }
                    }
                }
                with self.assertRaisesRegex(
                    DockerfileError,
                    "image tag must be literal and must not use variable syntax",
                ):
                    build_requests_from_topology(Path("/lab/lab.clab.yml"), data)

    def test_fixed_prefix_ignores_other_prefixes(self) -> None:
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
            requests = build_requests_from_topology(root / "lab.clab.yml", data)

        self.assertEqual(len(requests), 0)
