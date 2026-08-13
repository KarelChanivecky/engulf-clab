from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from engulf_clab_freeze.command import (
    FreezeError,
    _confirm_overwrite,
    _download_wheels,
    _launcher,
    freeze,
    main,
)


class FreezeCommandTestCase(unittest.TestCase):
    def test_main_detects_the_single_current_directory_topology_and_default_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")

            with (
                patch("engulf_clab_freeze.command.freeze") as mocked_freeze,
                patch("engulf_clab_lab_parser.session.Path.cwd", return_value=root),
            ):
                self.assertEqual(main([]), 0)

            mocked_freeze.assert_called_once_with(
                topology.resolve(),
                root / f"{root.name}.tar.gz",
                workspace=None,
                confirm_overwrite=_confirm_overwrite,
            )

    def test_main_accepts_an_explicit_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = root / "share.tar.gz"

            with patch("engulf_clab_freeze.command.freeze") as mocked_freeze:
                self.assertEqual(main(["--topology", str(topology), "--output", str(archive)]), 0)

            mocked_freeze.assert_called_once_with(
                topology.resolve(),
                archive.resolve(),
                workspace=None,
                confirm_overwrite=_confirm_overwrite,
            )

    def test_freeze_sanitizes_a_copy_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            original = {
                "name": "demo",
                "topology": {
                    "nodes": {
                        "router": {
                            "license": "$PERSONAL_POOL",
                            "env": {"ECLAB_LIC_CLAMP": "personal.lic"},
                        }
                    }
                },
            }
            topology.write_text(yaml.safe_dump(original), encoding="utf-8")
            (root / "private.lic").write_text("secret", encoding="utf-8")
            archive = Path(directory) / "share.tar.gz"
            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze(topology, archive)
            self.assertEqual(yaml.safe_load(topology.read_text(encoding="utf-8")), original)
            with tarfile.open(archive, "r:gz") as tar:
                names = tar.getnames()
                self.assertFalse(any(name.endswith("private.lic") for name in names))
                frozen = yaml.safe_load(tar.extractfile("share/lab.clab.yml").read())
            router = frozen["topology"]["nodes"]["router"]
            self.assertEqual(router["license"], "__ECLAB_LICENSE_PROMPT__")
            self.assertNotIn("ECLAB_LIC_CLAMP", router["env"])
            self.assertEqual(frozen["x-engulf-clab-freeze"]["licenses"], "prompt")

    def test_freeze_refuses_generated_license_copies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            (root / ".engulf-clab" / "licenses").mkdir(parents=True)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            with self.assertRaisesRegex(FreezeError, "destroy the lab"):
                freeze(topology, Path(directory) / "share.tar.gz")

    def test_existing_archive_is_left_unchanged_when_overwrite_is_declined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = root / "share.tar.gz"
            archive.write_bytes(b"previous archive")

            self.assertFalse(freeze(topology, archive, confirm_overwrite=lambda _path: False))
            self.assertEqual(archive.read_bytes(), b"previous archive")

    def test_existing_archive_is_excluded_when_overwrite_is_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = root / "share.tar.gz"
            archive.write_bytes(b"previous archive")

            with patch("engulf_clab_freeze.command._download_wheels"):
                self.assertTrue(freeze(topology, archive, confirm_overwrite=lambda _path: True))

            with tarfile.open(archive, "r:gz") as tar:
                self.assertFalse(any(name.endswith("/share.tar.gz") for name in tar.getnames()))

    def test_interactive_overwrite_prompt_accepts_yes(self) -> None:
        archive = Path("/tmp/share.tar.gz")
        stdin = SimpleNamespace(isatty=lambda: True)
        with (
            patch("engulf_clab_freeze.command.sys.stdin", stdin),
            patch("builtins.input", return_value="y") as prompt,
        ):
            self.assertTrue(_confirm_overwrite(archive))

        prompt.assert_called_once_with(
            "A file already exists at the output path: /tmp/share.tar.gz. Overwrite it (y/n)? "
        )

    def test_freeze_excludes_runtime_and_legacy_state_and_prunes_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text(
                "name: demo\ntopology: {nodes: {router: {}}}\n",
                encoding="utf-8",
            )
            outside = Path(directory) / "outside"
            outside.write_text("must not be accessed", encoding="utf-8")
            for name in (".forticlab", "clab-demo"):
                state = root / name
                state.mkdir()
                (state / "outside").symlink_to(outside)
            (root / "empty").mkdir()
            licenses = root / "licenses-only"
            licenses.mkdir()
            (licenses / "private.lic").write_text("secret", encoding="utf-8")
            archive = Path(directory) / "share.tar.gz"

            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze(topology, archive)

            with tarfile.open(archive, "r:gz") as tar:
                names = tar.getnames()

            def archived(path: str) -> bool:
                return any(name == f"share/{path}" or name.startswith(f"share/{path}/") for name in names)

            self.assertFalse(archived(".forticlab"))
            self.assertFalse(archived("clab-demo"))
            self.assertFalse(archived("empty"))
            self.assertFalse(archived("licenses-only"))


class WheelhouseTestCase(unittest.TestCase):
    def test_wheelhouse_seeds_local_wheels_before_downloading_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            source = staging / "engulf_clab-0.1.0-py3-none-any.whl"
            source.write_bytes(b"locally-built wheel")
            distribution = SimpleNamespace(
                read_text=lambda name: json.dumps({"url": source.as_uri()})
                if name == "direct_url.json"
                else None
            )
            warnings: list[str] = []
            with (
                patch(
                    "engulf_clab_freeze.command.importlib.metadata.distribution",
                    return_value=distribution,
                ),
                patch(
                    "engulf_clab_freeze.command.subprocess.run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
            ):
                _download_wheels(staging, [("engulf-clab", "0.1.0")], warnings)

            wheelhouse = staging / "wheelhouse"
            self.assertEqual((wheelhouse / source.name).read_bytes(), source.read_bytes())
            self.assertEqual(warnings, [])
            command = run.call_args.args[0]
            self.assertIn("--find-links", command)
            self.assertIn(str(wheelhouse), command)

    def test_incomplete_download_keeps_seeded_wheels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            source = staging / "engulf_clab-0.1.0-py3-none-any.whl"
            source.write_bytes(b"locally-built wheel")
            distribution = SimpleNamespace(
                read_text=lambda _name: json.dumps({"url": source.as_uri()})
            )
            warnings: list[str] = []
            with (
                patch(
                    "engulf_clab_freeze.command.importlib.metadata.distribution",
                    return_value=distribution,
                ),
                patch(
                    "engulf_clab_freeze.command.subprocess.run",
                    return_value=SimpleNamespace(returncode=1),
                ),
            ):
                _download_wheels(staging, [("engulf-clab", "0.1.0")], warnings)

            self.assertTrue((staging / "wheelhouse" / source.name).is_file())
            self.assertEqual(
                warnings,
                [
                    "could not obtain a complete wheelhouse; launcher will fall back to its package index"
                ],
            )

    def test_empty_incomplete_wheelhouse_is_removed_and_launcher_allows_that(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            distribution = SimpleNamespace(read_text=lambda _name: None)
            warnings: list[str] = []
            with (
                patch(
                    "engulf_clab_freeze.command.importlib.metadata.distribution",
                    return_value=distribution,
                ),
                patch(
                    "engulf_clab_freeze.command.subprocess.run",
                    return_value=SimpleNamespace(returncode=1),
                ),
            ):
                _download_wheels(staging, [("engulf-clab", "0.1.0")], warnings)

            self.assertFalse((staging / "wheelhouse").exists())
            self.assertIn('if [[ -d "$wheelhouse" ]]; then', _launcher("lab.clab.yml"))
