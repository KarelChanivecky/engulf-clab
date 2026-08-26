from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_docker_image_api import (
    ImageProvider,
    ImageRequirement,
    ProvisionAuthority,
    VrnetlabBuildRecipe,
)

from engulf_clab_vrnetlab_build.config import BuildRequest
from engulf_clab_vrnetlab_build.provider import VRNETLAB_PROVIDER_ID, VrnetlabBuildProvider


def _make_checkout(root: Path, vendor: str = "vendor", type_name: str = "router") -> Path:
    builder = root / vendor / type_name
    builder.mkdir(parents=True)
    (builder / "Makefile").write_text("all: ; @echo built\n")
    return builder


def _request(
    image: str = "vrnetlab/vr-router:1.0.0",
    source: Path | None = None,
    node_name: str = "router",
    builder_type: str = "vendor/router",
) -> BuildRequest:
    return BuildRequest(
        node_name=node_name,
        image=image,
        builder_type=builder_type,
        source=source,
    )


class VrnetlabBuildProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._checkout = TemporaryDirectory()
        self.addCleanup(self._checkout.cleanup)
        self.root = Path(self._checkout.name).resolve()
        _make_checkout(self.root)
        images = self.root / "images"
        images.mkdir(exist_ok=True)
        self.source = images / "router.qcow2"
        self.source.write_bytes(b"qcow2")
        self.provider = VrnetlabBuildProvider()

    def _refresh(self, *requests: BuildRequest) -> None:
        self.provider.refresh_requests(list(requests), checkout_context=str(self.root))

    def test_provider_implements_image_provider_protocol(self) -> None:
        self.assertIsInstance(self.provider, ImageProvider)

    def test_provide_returns_none_before_refresh(self) -> None:
        self.assertIsNone(self.provider.provide(ImageRequirement("vrnetlab/vr-router:1.0.0")))

    def test_provide_offers_recipe_for_refreshed_request(self) -> None:
        self._refresh(_request(source=self.source))

        response = self.provider.provide(ImageRequirement("vrnetlab/vr-router:1.0.0"))

        self.assertIsNotNone(response)
        assert response is not None
        self.assertIsNone(response.rejection)
        self.assertEqual(response.authority, ProvisionAuthority.PREFERRED)
        self.assertTrue(response.fallback_on_failure)
        provision = response.provision
        assert provision is not None
        self.assertEqual(provision.image, "vrnetlab/vr-router:1.0.0")
        recipe = provision.recipe
        self.assertIsInstance(recipe, VrnetlabBuildRecipe)
        assert isinstance(recipe, VrnetlabBuildRecipe)
        self.assertEqual(recipe.source, self.source)
        self.assertEqual(recipe.builder, self.root / "vendor" / "router")
        self.assertEqual(recipe.recipe_kind, "vrnetlab")
        self.assertEqual(provision.origin, "vrnetlab node router")

    def test_provide_returns_none_for_unrequested_reference(self) -> None:
        self._refresh(_request(source=self.source))
        self.assertIsNone(self.provider.provide(ImageRequirement("other/image:1.0.0")))

    def test_provide_returns_none_when_request_has_no_source(self) -> None:
        self._refresh(_request(source=None))
        self.assertIsNone(self.provider.provide(ImageRequirement("vrnetlab/vr-router:1.0.0")))

    def test_refresh_replaces_previous_requests(self) -> None:
        self._refresh(_request(source=self.source))
        self._refresh(_request(image="vrnetlab/vr-switch:2.0.0", source=self.source))

        self.assertIsNone(self.provider.provide(ImageRequirement("vrnetlab/vr-router:1.0.0")))
        self.assertIsNotNone(self.provider.provide(ImageRequirement("vrnetlab/vr-switch:2.0.0")))

    def test_clear_removes_all_requests(self) -> None:
        self._refresh(_request(source=self.source))
        self.provider.clear()

        self.assertIsNone(self.provider.provide(ImageRequirement("vrnetlab/vr-router:1.0.0")))
        self.assertIsNone(
            self.provider.provide(
                ImageRequirement("vrnetlab/vr-switch:2.0.0"),
            )
        )

    def test_missing_builder_directory_is_a_retryable_rejection(self) -> None:
        self._refresh(_request(builder_type="vendor/missing", source=self.source))

        response = self.provider.provide(ImageRequirement("vrnetlab/vr-router:1.0.0"))

        self.assertIsNotNone(response)
        assert response is not None
        self.assertIsNone(response.provision)
        self.assertFalse(response.terminal)
        self.assertEqual(response.authority, ProvisionAuthority.AUTHORITATIVE)
        self.assertIn("cannot resolve vrnetlab builder", str(response.rejection))

    def test_missing_checkout_context_is_a_retryable_rejection(self) -> None:
        self.provider.refresh_requests([_request(source=self.source)], checkout_context=None)

        response = self.provider.provide(ImageRequirement("vrnetlab/vr-router:1.0.0"))

        self.assertIsNotNone(response)
        assert response is not None
        self.assertIsNone(response.provision)
        self.assertFalse(response.terminal)

    def test_provider_id_is_stable(self) -> None:
        self.assertEqual(VRNETLAB_PROVIDER_ID, "org.engulf.docker.vrnetlab-build")


if __name__ == "__main__":
    unittest.main()
