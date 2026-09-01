from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from engulf_clab_image_archive.config import build_requests_from_topology
from engulf_clab_image_archive.errors import ImageArchiveError


def _topology(**environment: str) -> dict[str, Any]:
    return {
        "topology": {
            "nodes": {
                "router": {
                    "image": "example/router:1.0.0",
                    "env": dict(environment),
                }
            }
        }
    }


class BuildRequestsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        self.topology = self.root / "lab.clab.yml"
        self.archive = self.root / "images" / "router.tar.gz"
        self.archive.parent.mkdir()
        self.archive.write_bytes(b"archive")

    def _requests(self, **environment: str) -> list[Any]:
        return build_requests_from_topology(self.topology, _topology(**environment))

    def test_node_without_env_is_ignored(self) -> None:
        document: dict[str, Any] = {
            "topology": {"nodes": {"router": {"image": "example/router:1.0.0"}}}
        }

        self.assertEqual(build_requests_from_topology(self.topology, document), [])

    def test_node_without_archive_declaration_is_ignored(self) -> None:
        self.assertEqual(self._requests(OTHER="value"), [])

    def test_relative_archive_resolves_against_the_topology_directory(self) -> None:
        (request,) = self._requests(ECLAB_IMAGE_ARCHIVE="images/router.tar.gz")

        self.assertEqual(request.node_name, "router")
        self.assertEqual(request.image, "example/router:1.0.0")
        self.assertEqual(request.archive, self.archive)
        self.assertIsNone(request.source)
        self.assertFalse(request.reload)

    def test_absolute_archive_is_accepted(self) -> None:
        (request,) = self._requests(ECLAB_IMAGE_ARCHIVE=str(self.archive))

        self.assertEqual(request.archive, self.archive)

    def test_archive_reference_and_reload_are_recorded(self) -> None:
        (request,) = self._requests(
            ECLAB_IMAGE_ARCHIVE="images/router.tar.gz",
            ECLAB_IMAGE_ARCHIVE_REF="vendor/router:2026.08",
            ECLAB_IMAGE_ARCHIVE_RELOAD="true",
        )

        self.assertEqual(request.source, "vendor/router:2026.08")
        self.assertTrue(request.reload)

    def test_missing_archive_is_rejected(self) -> None:
        with self.assertRaisesRegex(ImageArchiveError, "does not exist"):
            self._requests(ECLAB_IMAGE_ARCHIVE="images/absent.tar.gz")

    def test_directory_archive_is_rejected(self) -> None:
        (self.root / "images" / "bundle.tar.gz").mkdir()

        with self.assertRaisesRegex(ImageArchiveError, "must name a file"):
            self._requests(ECLAB_IMAGE_ARCHIVE="images/bundle.tar.gz")

    def test_unsupported_suffix_is_rejected(self) -> None:
        disk = self.root / "images" / "router.qcow2"
        disk.write_bytes(b"qcow2")

        with self.assertRaisesRegex(ImageArchiveError, "must name a"):
            self._requests(ECLAB_IMAGE_ARCHIVE="images/router.qcow2")

    def test_every_supported_suffix_is_accepted(self) -> None:
        for name in (
            "a.tar",
            "b.tar.gz",
            "c.tgz",
            "d.tar.bz2",
            "e.tbz2",
            "f.tar.xz",
            "g.txz",
        ):
            with self.subTest(name=name):
                path = self.root / "images" / name
                path.write_bytes(b"archive")
                (request,) = self._requests(ECLAB_IMAGE_ARCHIVE=f"images/{name}")
                self.assertEqual(request.archive, path)

    def test_reference_without_archive_is_rejected(self) -> None:
        with self.assertRaisesRegex(ImageArchiveError, "but not ECLAB_IMAGE_ARCHIVE"):
            self._requests(ECLAB_IMAGE_ARCHIVE_REF="vendor/router:1.0.0")

    def test_reload_without_archive_is_rejected(self) -> None:
        with self.assertRaisesRegex(ImageArchiveError, "but not ECLAB_IMAGE_ARCHIVE"):
            self._requests(ECLAB_IMAGE_ARCHIVE_RELOAD="true")

    def test_invalid_reload_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(ImageArchiveError, "must be one of true"):
            self._requests(
                ECLAB_IMAGE_ARCHIVE="images/router.tar.gz",
                ECLAB_IMAGE_ARCHIVE_RELOAD="maybe",
            )

    def test_unexpanded_image_tag_is_rejected(self) -> None:
        document: dict[str, Any] = {
            "topology": {
                "nodes": {
                    "router": {
                        "image": "example/router:${TAG}",
                        "env": {"ECLAB_IMAGE_ARCHIVE": "images/router.tar.gz"},
                    }
                }
            }
        }

        with self.assertRaisesRegex(ImageArchiveError, "did not resolve to a literal"):
            build_requests_from_topology(self.topology, document)

    def test_node_without_image_is_rejected(self) -> None:
        document: dict[str, Any] = {
            "topology": {
                "nodes": {
                    "router": {"env": {"ECLAB_IMAGE_ARCHIVE": "images/router.tar.gz"}}
                }
            }
        }

        with self.assertRaisesRegex(ImageArchiveError, "has no image tag"):
            build_requests_from_topology(self.topology, document)

    def test_unexpanded_archive_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(ImageArchiveError, "did not resolve to a literal"):
            self._requests(
                ECLAB_IMAGE_ARCHIVE="images/router.tar.gz",
                ECLAB_IMAGE_ARCHIVE_REF="vendor/router:${TAG}",
            )

    def test_non_mapping_env_is_rejected(self) -> None:
        document: dict[str, Any] = {
            "topology": {
                "nodes": {"router": {"image": "example/router:1.0.0", "env": ["nope"]}}
            }
        }

        with self.assertRaisesRegex(ImageArchiveError, "env must be a YAML mapping"):
            build_requests_from_topology(self.topology, document)

    def test_missing_topology_mapping_is_rejected(self) -> None:
        with self.assertRaisesRegex(ImageArchiveError, "missing topology mapping"):
            build_requests_from_topology(self.topology, {})
