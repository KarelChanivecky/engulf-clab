from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_consumption.collector import (
    classify_image_usage,
    collect,
    directory_size,
    running_labs,
    selected_lab,
    totals,
)
from engulf_clab_consumption.command import main, render
from engulf_clab_consumption.model import Container, ImageUsage, Lab, RuntimeStats


class FakeDocker:
    def __init__(self) -> None:
        self.container_values: tuple[Container, ...] = ()
        self.images: dict[str, ImageUsage] = {}
        self.stats_values: dict[str, RuntimeStats] = {}
        self.references: dict[str, str] = {}

    def containers(self) -> tuple[Container, ...]:
        return self.container_values

    def image_usage(self, containers: tuple[Container, ...] = ()) -> dict[str, ImageUsage]:
        del containers
        return self.images

    def stats(self, identifiers: tuple[str, ...]) -> dict[str, RuntimeStats]:
        return {key: self.stats_values[key] for key in identifiers if key in self.stats_values}

    def resolve_images(self, references: tuple[str, ...]) -> dict[str, str]:
        return {reference: self.references[reference] for reference in references if reference in self.references}


class AccountingTest(unittest.TestCase):
    def test_aggregates_runtime_and_splits_image_storage(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").write_bytes(b"x")
            docker = FakeDocker()
            docker.stats_values = {
                "a": RuntimeStats(12.5, 100),
                "b": RuntimeStats(7.5, 200),
            }
            docker.images = {
                "image-a": ImageUsage("image-a", 1000, 400, 600),
                "image-b": ImageUsage("image-b", 2000, 500, 1500),
            }
            lab = Lab("demo", root, frozenset(docker.images), ("a", "b"))

            row = collect((lab,), docker, image_usage=docker.images)[0]

            self.assertEqual(row.cpu_percent, 20.0)
            self.assertEqual(row.memory_bytes, 300)
            self.assertEqual(row.unique_image_bytes, 2100)
            self.assertEqual(row.shared_image_bytes, 900)
            assert row.directory_bytes is not None
            self.assertEqual(row.storage_bytes, row.directory_bytes + 3000)

    def test_total_deduplicates_an_image_used_by_two_labs(self) -> None:
        docker = FakeDocker()
        docker.images = {"same": ImageUsage("same", 1000, 400, 600)}
        labs = (
            Lab("a", None, frozenset({"same"}), ()),
            Lab("b", None, frozenset({"same"}), ()),
        )
        classified = classify_image_usage(docker.images, labs)
        rows = collect(labs, docker, image_usage=classified)

        total = totals(rows, classified)

        self.assertEqual(rows[0].unique_image_bytes, 0)
        self.assertEqual(rows[0].shared_image_bytes, 1000)
        self.assertEqual(rows[1].shared_image_bytes, 1000)
        self.assertEqual(total.shared_image_bytes, 1000)
        self.assertIsNone(total.storage_bytes)

    def test_single_lab_owns_complete_image_despite_daemon_layer_sharing(self) -> None:
        usage = {"image": ImageUsage("image", 1000, 900, 100)}
        labs = (Lab("only", None, frozenset({"image"}), ()),)

        classified = classify_image_usage(usage, labs)

        self.assertEqual(classified["image"].unique, 1000)
        self.assertEqual(classified["image"].shared, 0)

    def test_unavailable_image_split_is_not_reported_as_zero(self) -> None:
        docker = FakeDocker()
        docker.images = {"image": ImageUsage("image", 1000, None, None)}

        row = collect(
            (Lab("demo", None, frozenset({"image"}), ()),),
            docker,
            image_usage=docker.images,
        )[0]

        self.assertIsNone(row.unique_image_bytes)
        self.assertIsNone(row.shared_image_bytes)
        self.assertIn("N/A means", render((row,)))

    def test_directory_size_does_not_follow_symlinks_or_repeat_hard_links(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "data"
            original.write_bytes(b"x" * 4096)
            (root / "hard-link").hardlink_to(original)
            (root / "symbolic-link").symlink_to(original)

            measured = directory_size(root)

            self.assertIsNotNone(measured)
            assert measured is not None
            self.assertGreaterEqual(measured, 4096)
            self.assertLess(measured, 8192 + root.lstat().st_blocks * 512)


class SelectionTest(unittest.TestCase):
    def test_all_groups_only_running_containers(self) -> None:
        topology = Path("/labs/demo/demo.clab.yml")
        containers = (
            Container("a", "demo", topology, "one", "one:latest", True),
            Container("b", "demo", topology, "two", "two:latest", False),
            Container("c", "other", Path("/labs/other/lab.clab.yml"), "three", "three:latest", True),
        )

        labs = running_labs(containers)

        self.assertEqual([lab.name for lab in labs], ["demo", "other"])
        self.assertEqual(labs[0].image_ids, frozenset({"one"}))

    def test_selected_stopped_lab_resolves_explicit_topology_images(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            topology = root / "demo.clab.yml"
            topology.write_text(
                "name: demo\ntopology:\n  nodes:\n    router:\n      image: example/router:1\n",
                encoding="utf-8",
            )
            docker = FakeDocker()
            docker.references = {"example/router:1": "sha256:abc"}

            lab = selected_lab(topology, (), docker, {})

            self.assertEqual(lab.name, "demo")
            self.assertEqual(lab.image_ids, frozenset({"sha256:abc"}))
            self.assertEqual(lab.running_container_ids, ())

    def test_selected_lab_resolves_default_and_kind_images(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            topology = root / "demo.clab.yml"
            topology.write_text(
                """name: demo
defaults:
  image: example/default:1
kinds:
  linux:
    image: example/linux:1
topology:
  nodes:
    default-node: {}
    linux-node:
      kind: linux
""",
                encoding="utf-8",
            )
            docker = FakeDocker()
            docker.references = {
                "example/default:1": "sha256:default",
                "example/linux:1": "sha256:linux",
            }

            lab = selected_lab(topology, (), docker, {})

            self.assertEqual(
                lab.image_ids, frozenset({"sha256:default", "sha256:linux"})
            )

    def test_selected_running_lab_uses_container_image_id_over_retargeted_tag(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            topology = root / "demo.clab.yml"
            topology.write_text(
                "name: demo\ntopology:\n  nodes:\n    router:\n      image: example/router:1\n",
                encoding="utf-8",
            )
            container = Container(
                "container",
                "demo",
                topology,
                "sha256:deployed",
                "example/router:1",
                True,
            )
            docker = FakeDocker()
            docker.references = {"example/router:1": "sha256:retargeted"}

            lab = selected_lab(topology, (container,), docker, {})

            self.assertEqual(lab.image_ids, frozenset({"sha256:deployed"}))


class CommandTest(unittest.TestCase):
    def test_single_sample_prints_table_and_total(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "demo.clab.yml").write_text(
                "name: demo\ntopology:\n  nodes: {}\n", encoding="utf-8"
            )
            output = io.StringIO()

            code = main((), cwd=root, environment={}, docker=FakeDocker(), output=output)

            self.assertEqual(code, 0)
            self.assertIn("IMAGES UNIQUE", output.getvalue())
            self.assertIn("demo", output.getvalue())
            self.assertIn("TOTAL", output.getvalue())

    def test_poll_waits_two_seconds_and_ctrl_c_is_clean(self) -> None:
        output = io.StringIO()
        delays: list[int] = []

        def stop(delay: int) -> None:
            delays.append(delay)
            raise KeyboardInterrupt

        code = main(
            ("--all", "-p"),
            cwd=Path.cwd(),
            environment={},
            docker=FakeDocker(),
            output=output,
            sleep=stop,
        )

        self.assertEqual(code, 0)
        self.assertEqual(delays, [2])
        self.assertIn("TOTAL", output.getvalue())

    def test_topology_and_all_conflict(self) -> None:
        with self.assertRaises(SystemExit):
            main(
                ("-t", "lab.clab.yml", "--all"),
                cwd=Path.cwd(),
                environment={},
                docker=FakeDocker(),
            )


if __name__ == "__main__":
    unittest.main()
