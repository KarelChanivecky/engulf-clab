from __future__ import annotations

import unittest
from pathlib import Path

from engulf_docker_image_api import (
    DockerArchiveRecipe,
    DockerfileRecipe,
    DockerPullRecipe,
    ImageBuildGraph,
    ImageParameter,
    ImageProviderPlugin,
    ImageProviderResponse,
    ImageProvision,
    ImageRecipe,
    ImageRequirement,
    ProvisionAuthority,
    RegisteredImageProvider,
    VrnetlabBuildRecipe,
    canonical_image_reference,
)


class _Provider:
    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
        del requirement
        return None


class ContractTest(unittest.TestCase):
    def test_graph_and_provider_are_application_neutral(self) -> None:
        recipe = DockerfileRecipe(Path("/work/Dockerfile"), Path("/work"))
        requirement = ImageRequirement(
            "example/root",
            (ImageParameter("release", "2026.08"),),
            "json document",
        )
        provision = ImageProvision("example/root:latest", recipe)

        graph = ImageBuildGraph((requirement,), (provision,))
        provider = RegisteredImageProvider("org.example.images", _Provider())

        self.assertEqual(graph.roots[0].origin, "json document")
        self.assertEqual(provider.provider_id, "org.example.images")
        self.assertEqual(
            ImageProviderPlugin("org.example.images", provider.provider).goal_requirement.goal_id,
            "org.engulf.docker-image",
        )
        self.assertEqual(
            canonical_image_reference("localhost:5000/example/root"),
            "localhost:5000/example/root:latest",
        )

    def test_provider_response_is_exclusive(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            ImageProviderResponse()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            ImageProviderResponse(
                ImageProvision(
                    "example/root",
                    DockerfileRecipe(Path("/work/Dockerfile"), Path("/work")),
                ),
                "no",
            )

    def test_pull_recipe_and_ranked_response_are_immutable_contract_values(self) -> None:
        response = ImageProviderResponse.offer(
            ImageProvision("example/root", DockerPullRecipe("mirror.local/example/root")),
            authority=ProvisionAuthority.PREFERRED,
        )

        assert response.provision is not None
        self.assertEqual(response.provision.recipe.source, "mirror.local/example/root:latest")
        self.assertFalse(response.provision.recipe.only_if_missing)
        self.assertEqual(response.authority, ProvisionAuthority.PREFERRED)
        self.assertTrue(response.fallback_on_failure)

        local_first = DockerPullRecipe("example/root", only_if_missing=True)
        self.assertTrue(local_first.only_if_missing)
        with self.assertRaisesRegex(TypeError, "must be a boolean"):
            DockerPullRecipe("example/root", only_if_missing=1)  # type: ignore[arg-type]

    def test_archive_recipe_keeps_an_absolute_path_and_canonical_source(self) -> None:
        recipe = DockerArchiveRecipe(Path("/images/root.tar.gz"), "vendor/root")

        self.assertEqual(recipe.archive, Path("/images/root.tar.gz"))
        self.assertEqual(recipe.source, "vendor/root:latest")
        self.assertFalse(recipe.only_if_missing)
        self.assertIsNone(DockerArchiveRecipe(Path("/images/root.tar.gz")).source)

        with self.assertRaisesRegex(ValueError, "must be absolute"):
            DockerArchiveRecipe(Path("images/root.tar.gz"))
        with self.assertRaisesRegex(TypeError, "must be a boolean"):
            DockerArchiveRecipe(
                Path("/images/root.tar.gz"), only_if_missing=1  # type: ignore[arg-type]
            )

    def test_terminal_rejections_cannot_be_offers(self) -> None:
        with self.assertRaisesRegex(ValueError, "terminal rejection"):
            ImageProviderResponse(
                provision=ImageProvision(
                    "example/root",
                    DockerPullRecipe("example/root"),
                ),
                terminal=True,
            )

    def test_every_recipe_satisfies_the_image_recipe_protocol(self) -> None:
        recipes = (
            DockerfileRecipe(Path("/work/Dockerfile"), Path("/work")),
            DockerPullRecipe("example/root"),
            DockerArchiveRecipe(Path("/images/root.tar.gz")),
            VrnetlabBuildRecipe(
                Path("/images/root.qcow2"), Path("/vrnetlab/vendor/router"), "example/root"
            ),
        )

        for recipe in recipes:
            with self.subTest(recipe=type(recipe).__name__):
                self.assertIsInstance(recipe, ImageRecipe)
                self.assertEqual(recipe.recipe_kind, type(recipe).recipe_kind)
                self.assertIsInstance(recipe.recipe_kind, str)

    def test_recipe_kinds_are_distinct(self) -> None:
        kinds = {
            DockerfileRecipe.recipe_kind,
            DockerPullRecipe.recipe_kind,
            DockerArchiveRecipe.recipe_kind,
            VrnetlabBuildRecipe.recipe_kind,
        }
        self.assertEqual(len(kinds), 4)

    def test_provision_rejects_values_outside_the_recipe_protocol(self) -> None:
        for bad in (None, "dockerfile", object(), 42):
            with self.subTest(value=bad), self.assertRaisesRegex(TypeError, "ImageRecipe protocol"):
                ImageProvision("example/root", bad)

    def test_custom_recipe_implementations_are_accepted(self) -> None:
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _CustomRecipe:
            payload: str

            recipe_kind = "custom"

        provision = ImageProvision("example/root", _CustomRecipe("anything"))

        self.assertEqual(provision.recipe.recipe_kind, "custom")


if __name__ == "__main__":
    unittest.main()
