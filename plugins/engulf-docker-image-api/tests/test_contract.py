from __future__ import annotations

import unittest
from pathlib import Path

from engulf_docker_image_api import (
    DockerfileRecipe,
    DockerPullRecipe,
    ImageBuildGraph,
    ImageParameter,
    ImageProviderPlugin,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    RegisteredImageProvider,
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
        self.assertEqual(response.authority, ProvisionAuthority.PREFERRED)
        self.assertTrue(response.fallback_on_failure)

    def test_terminal_rejections_cannot_be_offers(self) -> None:
        with self.assertRaisesRegex(ValueError, "terminal rejection"):
            ImageProviderResponse(
                provision=ImageProvision(
                    "example/root",
                    DockerPullRecipe("example/root"),
                ),
                terminal=True,
            )


if __name__ == "__main__":
    unittest.main()
