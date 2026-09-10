from __future__ import annotations

import unittest

from engulf_clab_consumption.docker import DockerClient, parse_size
from engulf_clab_consumption.model import Container


class StubDocker(DockerClient):
    def __init__(self, outputs: dict[tuple[str, ...], str]) -> None:
        self.outputs = outputs

    def _run(self, arguments: tuple[str, ...]) -> str:
        return self.outputs[arguments]


class ParseTest(unittest.TestCase):
    def test_sizes_support_decimal_and_binary_units(self) -> None:
        self.assertEqual(parse_size("1.5 kB"), 1500)
        self.assertEqual(parse_size("1.5 KiB"), 1536)
        self.assertEqual(parse_size(42), 42)
        self.assertIsNone(parse_size("N/A"))

    def test_image_usage_accepts_json_records(self) -> None:
        docker = StubDocker(
            {
                ("system", "df", "--verbose", "--format", "json"): (
                    '{"ID":"sha256:abc","Size":"10MB","SharedSize":"4MB","UniqueSize":"6MB"}\n'
                )
            }
        )

        usage = docker.image_usage()

        self.assertEqual(usage["sha256:abc"].size, 10_000_000)
        self.assertEqual(usage["abc"].shared, 4_000_000)

    def test_image_usage_falls_back_to_retained_container_rootfs(self) -> None:
        docker = StubDocker(
            {("system", "df", "--verbose", "--format", "json"): '{"Images":[]}'}
        )
        container = Container(
            "container", "demo", None, "sha256:gone", "example:old", True, 1234
        )

        usage = docker.image_usage((container,))

        self.assertEqual(usage["gone"].size, 1234)
        self.assertIsNone(usage["gone"].shared)

    def test_containers_capture_retained_image_size(self) -> None:
        docker = StubDocker(
            {
                (
                    "container",
                    "ls",
                    "--all",
                    "--filter",
                    "label=containerlab",
                    "--quiet",
                    "--no-trunc",
                ): "container\n",
                ("container", "inspect", "--size", "container"): (
                    '[{"Id":"container","Image":"sha256:gone",'
                    '"SizeRootFs":1200,"SizeRw":200,'
                    '"Config":{"Image":"example:old",'
                    '"Labels":{"containerlab":"demo"}},'
                    '"State":{"Running":true}}]'
                ),
            }
        )

        containers = docker.containers()

        self.assertEqual(containers[0].retained_image_bytes, 1000)

    def test_stats_parse_json_lines(self) -> None:
        docker = StubDocker(
            {
                ("stats", "--no-stream", "--no-trunc", "--format", "json", "abc"): (
                    '{"ID":"abc","CPUPerc":"12.50%","MemUsage":"1.5MiB / 2GiB"}\n'
                )
            }
        )

        stats = docker.stats(("abc",))

        self.assertEqual(stats["abc"].cpu_percent, 12.5)
        self.assertEqual(stats["abc"].memory_bytes, 1_572_864)


if __name__ == "__main__":
    unittest.main()
