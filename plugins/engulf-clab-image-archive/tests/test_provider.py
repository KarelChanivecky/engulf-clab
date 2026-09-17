from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_docker_image_api import (
    DockerArchiveRecipe,
    ImageProvider,
    ImageRequirement,
    ProvisionAuthority,
)

from engulf_clab_image_archive.config import ArchiveRequest
from engulf_clab_image_archive.errors import ImageArchiveError
from engulf_clab_image_archive.provider import ImageArchiveProvider


class ImageArchiveProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name).resolve()
        self.archive = self.root / "router.tar.gz"
        self.archive.write_bytes(b"archive")
        self.provider = ImageArchiveProvider()

    def _request(self, **overrides: object) -> ArchiveRequest:
        values: dict[str, object] = {
            "node_name": "router",
            "image": "example/router:1.0.0",
            "archive": self.archive,
        }
        values.update(overrides)
        return ArchiveRequest(**values)  # type: ignore[arg-type]

    def test_provider_implements_image_provider_protocol(self) -> None:
        self.assertIsInstance(self.provider, ImageProvider)

    def test_provide_returns_none_before_refresh(self) -> None:
        self.assertIsNone(self.provider.provide(ImageRequirement("example/router:1.0.0")))

    def test_provide_offers_a_load_recipe_for_a_refreshed_request(self) -> None:
        self.provider.refresh_requests([self._request()])

        response = self.provider.provide(ImageRequirement("example/router:1.0.0"))

        assert response is not None
        self.assertIsNone(response.rejection)
        self.assertEqual(response.authority, ProvisionAuthority.PREFERRED)
        self.assertFalse(response.fallback_on_failure)
        provision = response.provision
        assert provision is not None
        self.assertEqual(provision.image, "example/router:1.0.0")
        self.assertEqual(provision.origin, "image archive node router")
        recipe = provision.recipe
        assert isinstance(recipe, DockerArchiveRecipe)
        self.assertEqual(recipe.recipe_kind, "archive")
        self.assertEqual(recipe.archive, self.archive)
        self.assertIsNone(recipe.source)
        self.assertTrue(recipe.only_if_missing)

    def test_reload_request_always_loads(self) -> None:
        self.provider.refresh_requests([self._request(reload=True)])

        response = self.provider.provide(ImageRequirement("example/router:1.0.0"))

        assert response is not None and response.provision is not None
        recipe = response.provision.recipe
        assert isinstance(recipe, DockerArchiveRecipe)
        self.assertFalse(recipe.only_if_missing)

    def test_archive_reference_becomes_the_recipe_source(self) -> None:
        self.provider.refresh_requests([self._request(source="vendor/router:2026.08")])

        response = self.provider.provide(ImageRequirement("example/router:1.0.0"))

        assert response is not None and response.provision is not None
        recipe = response.provision.recipe
        assert isinstance(recipe, DockerArchiveRecipe)
        self.assertEqual(recipe.source, "vendor/router:2026.08")

    def test_implicit_latest_matches_a_recorded_bare_reference(self) -> None:
        self.provider.refresh_requests([self._request(image="example/router")])

        response = self.provider.provide(ImageRequirement("example/router:latest"))

        assert response is not None and response.provision is not None
        self.assertEqual(response.provision.image, "example/router:latest")

    def test_provide_returns_none_for_an_unrequested_reference(self) -> None:
        self.provider.refresh_requests([self._request()])

        self.assertIsNone(self.provider.provide(ImageRequirement("other/image:1.0.0")))

    def test_conflicting_canonical_requests_are_rejected_with_both_nodes(self) -> None:
        other_archive = self.root / "other.tar.gz"
        other_archive.write_bytes(b"different archive")

        with self.assertRaisesRegex(
            ImageArchiveError,
            r"conflicting image archive declarations.*router.*switch",
        ):
            self.provider.refresh_requests(
                [
                    self._request(node_name="router", image="example/router:latest"),
                    self._request(
                        node_name="switch",
                        image="example/router",
                        archive=other_archive,
                    ),
                ]
            )

    def test_identical_canonical_requests_may_reuse_one_archive(self) -> None:
        self.provider.refresh_requests(
            [
                self._request(node_name="router", image="example/router:latest"),
                self._request(node_name="switch", image="example/router"),
            ]
        )

        response = self.provider.provide(ImageRequirement("example/router:latest"))

        assert response is not None and response.provision is not None
        self.assertEqual(response.provision.origin, "image archive node router")

    def test_refresh_replaces_previous_requests(self) -> None:
        self.provider.refresh_requests([self._request()])
        self.provider.refresh_requests([self._request(image="example/switch:2.0.0")])

        self.assertIsNone(self.provider.provide(ImageRequirement("example/router:1.0.0")))
        self.assertIsNotNone(self.provider.provide(ImageRequirement("example/switch:2.0.0")))

    def test_clear_removes_all_requests(self) -> None:
        self.provider.refresh_requests([self._request()])
        self.provider.clear()

        self.assertIsNone(self.provider.provide(ImageRequirement("example/router:1.0.0")))
