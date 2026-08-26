from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_docker_image_api import (
    DockerfileRecipe,
    ImageBuildGraph,
    ImageParameter,
    ImageProviderResponse,
    ImageProvision,
    ImageRequirement,
    ProvisionAuthority,
    RegisteredImageProvider,
)

from engulf_docker_image_core import ImageResolutionError, resolve_image_graph


class _Provider:
    def __init__(self, root: Path, recipes: dict[str, str | Exception]) -> None:
        self.root = root
        self.recipes = recipes
        self.seen: list[ImageRequirement] = []

    def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
        self.seen.append(requirement)
        value = self.recipes.get(requirement.canonical_reference)
        if value is None:
            return None
        if isinstance(value, Exception):
            return ImageProviderResponse.reject(str(value), terminal=False)
        directory = self.root / requirement.canonical_reference.replace("/", "_").replace(":", "_")
        directory.mkdir()
        dockerfile = directory / "Dockerfile"
        dockerfile.write_text(value, encoding="utf-8")
        return ImageProviderResponse.offer(
            ImageProvision(requirement.canonical_reference, DockerfileRecipe(dockerfile, directory))
        )


class ResolverTest(unittest.TestCase):
    def test_recursively_provides_from_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = _Provider(
                root,
                {
                    "example/app:latest": "FROM example/base\n",
                    "example/base:latest": "FROM scratch\n",
                },
            )
            graph = resolve_image_graph(
                ImageBuildGraph((ImageRequirement("example/app"),)),
                (RegisteredImageProvider("org.example.provider", provider),),
            )

        self.assertEqual(graph.image("example/app").dependencies, ("example/base:latest",))
        self.assertFalse(graph.image("example/base").external)

    def test_requirement_parameters_do_not_flow_to_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = _Provider(
                root,
                {
                    "example/app:latest": "FROM example/base\n",
                    "example/base:latest": "FROM scratch\n",
                },
            )
            resolve_image_graph(
                ImageBuildGraph(
                    (
                        ImageRequirement(
                            "example/app",
                            (ImageParameter("release", "42"),),
                        ),
                    )
                ),
                (RegisteredImageProvider("org.example.provider", provider),),
            )

        self.assertEqual(provider.seen[0].parameters[0].value, "42")
        self.assertEqual(provider.seen[1].parameters, ())

    def test_rejection_backtracks_to_later_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rejecting = _Provider(root, {"example/app:latest": RuntimeError("unsupported")})
            fallback = _Provider(root, {"example/app:latest": "FROM scratch\n"})
            graph = resolve_image_graph(
                ImageBuildGraph((ImageRequirement("example/app"),)),
                (
                    RegisteredImageProvider("org.example.rejecting", rejecting, 100),
                    RegisteredImageProvider("org.example.fallback", fallback, 10),
                ),
            )
        self.assertEqual(graph.image("example/app").provider_id, "org.example.fallback")

    def test_recursive_failure_backtracks_without_orphan_builds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferred = _Provider(
                root / "preferred",
                {
                    "example/app:latest": "FROM preferred/missing\n",
                    "preferred/missing:latest": RuntimeError("missing input"),
                },
            )
            preferred.root.mkdir()
            fallback = _Provider(root / "fallback", {"example/app:latest": "FROM scratch\n"})
            fallback.root.mkdir()
            graph = resolve_image_graph(
                ImageBuildGraph((ImageRequirement("example/app"),)),
                (
                    RegisteredImageProvider("org.example.preferred", preferred, 100),
                    RegisteredImageProvider("org.example.fallback", fallback, 10),
                ),
            )

        self.assertEqual(graph.image("example/app").provider_id, "org.example.fallback")
        self.assertEqual(tuple(item.image for item in graph.images), ("example/app:latest",))

    def test_authoritative_rejection_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _Provider(
                Path(directory), {"example/app:latest": RuntimeError("unknown recipe")}
            )
            with self.assertRaisesRegex(ImageResolutionError, "unknown recipe"):
                resolve_image_graph(
                    ImageBuildGraph((ImageRequirement("example/app"),)),
                    (RegisteredImageProvider("org.example.provider", provider),),
                )

    def test_response_authority_precedes_provider_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ordinary = _Provider(root / "ordinary", {"example/app:latest": "FROM scratch\n"})
            ordinary.root.mkdir()
            preferred = _Provider(root / "preferred", {"example/app:latest": "FROM scratch\n"})
            preferred.root.mkdir()

            class Preferred:
                def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
                    response = preferred.provide(requirement)
                    if response is None or response.provision is None:
                        return response
                    return ImageProviderResponse.offer(
                        response.provision,
                        authority=ProvisionAuthority.PREFERRED,
                    )

            graph = resolve_image_graph(
                ImageBuildGraph((ImageRequirement("example/app"),)),
                (
                    RegisteredImageProvider("org.example.ordinary", ordinary, 100),
                    RegisteredImageProvider("org.example.preferred", Preferred(), 1),
                ),
            )

        self.assertEqual(graph.image("example/app").provider_id, "org.example.preferred")

    def test_terminal_rejection_blocks_same_or_lower_authority_offer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rejecting = _Provider(root / "rejecting", {})
            fallback = _Provider(root / "fallback", {"example/app:latest": "FROM scratch\n"})
            rejecting.root.mkdir()
            fallback.root.mkdir()

            class Rejecting:
                def provide(self, requirement: ImageRequirement) -> ImageProviderResponse | None:
                    del requirement
                    return ImageProviderResponse.reject("owned namespace has no such tag")

            with self.assertRaisesRegex(ImageResolutionError, "owned namespace"):
                resolve_image_graph(
                    ImageBuildGraph((ImageRequirement("example/app"),)),
                    (
                        RegisteredImageProvider("org.example.rejecting", Rejecting()),
                        RegisteredImageProvider("org.example.fallback", fallback),
                    ),
                )


if __name__ == "__main__":
    unittest.main()
