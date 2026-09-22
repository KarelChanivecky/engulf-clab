from __future__ import annotations

import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_executable_wrapper_api import CompletionContext, Shell

from engulf_clab_vrnetlab_build.errors import VrnetlabError
from engulf_clab_vrnetlab_build.options import (
    IMAGE_OPTION,
    complete_image_option,
    parse_image_options,
)


class ImageOptionParsingTest(unittest.TestCase):
    def test_extracts_repeatable_assignment_and_separate_forms(self) -> None:
        parsed = parse_image_options(
            (
                "deploy",
                IMAGE_OPTION,
                "edge-1=/images/one.qcow2",
                f"{IMAGE_OPTION}=default=/images/default.qcow2",
                "-t",
                "lab.clab.yml",
            )
        )

        self.assertEqual(parsed.arguments, ("deploy", "-t", "lab.clab.yml"))
        self.assertEqual(
            dict(parsed.selectors),
            {
                "edge-1": "/images/one.qcow2",
                "default": "/images/default.qcow2",
            },
        )
        self.assertEqual(parsed.removals, frozenset({1, 2, 3}))

    def test_normalizes_legacy_bare_path_to_default(self) -> None:
        parsed = parse_image_options(("deploy", IMAGE_OPTION, "/images/router.qcow2"))

        self.assertEqual(dict(parsed.selectors), {"default": "/images/router.qcow2"})

    def test_rejects_missing_empty_and_duplicate_selectors(self) -> None:
        invalid = (
            ("deploy", IMAGE_OPTION),
            ("deploy", f"{IMAGE_OPTION}=default="),
            (
                "deploy",
                f"{IMAGE_OPTION}=default=/one.qcow2",
                f"{IMAGE_OPTION}=default=/two.qcow2",
            ),
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(VrnetlabError):
                parse_image_options(arguments)

    def test_does_not_consume_options_after_separator(self) -> None:
        arguments = ("deploy", "--", IMAGE_OPTION, "edge=/images/edge.qcow2")

        parsed = parse_image_options(arguments)

        self.assertEqual(parsed.arguments, arguments)
        self.assertEqual(dict(parsed.selectors), {})


class ImageOptionCompletionTest(unittest.TestCase):
    @staticmethod
    def _context(*words: str) -> CompletionContext:
        return CompletionContext(Shell.BASH, "eclab", "containerlab", words, len(words) - 1)

    def test_completes_default_and_opted_in_topology_nodes(self) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            topology.write_text(
                """
name: selector-lab
topology:
  nodes:
    edge-1:
      image: vrnetlab/edge:1
      env:
        ECLAB_VRNETLAB_TYPE: vendor/edge
    edge-2:
      image: vrnetlab/edge:2
      env:
        ECLAB_VRNETLAB_TYPE: vendor/edge
    client:
      image: alpine:latest
""",
                encoding="utf-8",
            )

            candidates = complete_image_option(self._context("deploy", "-t", str(topology), ""))

        self.assertEqual(
            [candidate.value for candidate in candidates],
            ["default=", "edge-1=", "edge-2="],
        )

    def test_completes_nodes_from_the_only_topology_in_cwd(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lab.clab.yml").write_text(
                """
name: selector-lab
topology:
  nodes:
    edge-1:
      image: vrnetlab/edge:1
      env:
        ECLAB_VRNETLAB_TYPE: vendor/edge
    client:
      image: alpine:latest
""",
                encoding="utf-8",
            )

            with chdir(root):
                candidates = complete_image_option(self._context("deploy", ""))

        self.assertEqual(
            [candidate.value for candidate in candidates],
            ["default=", "edge-1="],
        )

    def test_uses_context_cwd_without_changing_process_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lab.clab.yml").write_text(
                """
name: selector-lab
topology:
  nodes:
    edge-1:
      image: vrnetlab/edge:1
      env:
        ECLAB_VRNETLAB_TYPE: vendor/edge
""",
                encoding="utf-8",
            )
            context = CompletionContext(
                Shell.BASH,
                "eclab",
                "containerlab",
                ("deploy", ""),
                1,
                cwd=str(root),
                environment=(),
            )
            candidates = complete_image_option(context)

        self.assertEqual(
            [candidate.value for candidate in candidates], ["default=", "edge-1="]
        )

    def test_omits_selector_already_used_and_completes_from_topology_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text(
                """
name: selector-lab
topology:
  nodes:
    edge-1:
      image: vrnetlab/edge:1
      env:
        ECLAB_VRNETLAB_TYPE: vendor/edge
    edge-2:
      image: vrnetlab/edge:2
      env:
        ECLAB_VRNETLAB_TYPE: vendor/edge
""",
                encoding="utf-8",
            )
            images = root / "images"
            images.mkdir()
            source = images / "edge-2.qcow2"
            source.touch()

            targets = complete_image_option(
                self._context(
                    "deploy",
                    "-t",
                    str(topology),
                    IMAGE_OPTION,
                    "edge-1=/images/edge-1.qcow2",
                    IMAGE_OPTION,
                    "",
                )
            )
            paths = complete_image_option(
                self._context("deploy", "-t", str(topology), "edge-2=images/edge")
            )

        self.assertEqual(
            [candidate.value for candidate in targets],
            ["default=", "edge-2="],
        )
        self.assertEqual([candidate.value for candidate in paths], ["edge-2=images/edge-2.qcow2"])


if __name__ == "__main__":
    unittest.main()
