from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

import yaml
from engulf_clab_freeze.command import (
    FreezeError,
    _bundle_offline_images,
    _bundle_offline_vrnetlab,
    _confirm_overwrite,
    _copy_external_vrnetlab_inputs,
    _download_wheels,
    _launcher,
    _offline_image_references,
    _remove_offline_vrnetlab_inputs,
    freeze,
    main,
)


class FreezeCommandTestCase(unittest.TestCase):
    def test_main_returns_argparse_exit_codes_instead_of_exiting_the_plugin(
        self,
    ) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--help"], program="fclab freeze"), 0)
        self.assertIn("usage: fclab freeze", output.getvalue())

    def test_main_detects_the_single_current_directory_topology_and_default_archive(
        self,
    ) -> None:
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
                offline=False,
                user_state=None,
                application_name="eclab",
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
            )

    def test_main_accepts_an_explicit_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = root / "share.tar.gz"

            with patch("engulf_clab_freeze.command.freeze") as mocked_freeze:
                self.assertEqual(
                    main(["--topology", str(topology), "--output", str(archive)]), 0
                )

            mocked_freeze.assert_called_once_with(
                topology.resolve(),
                archive.resolve(),
                workspace=None,
                confirm_overwrite=_confirm_overwrite,
                offline=False,
                user_state=None,
                application_name="eclab",
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
            )

    def test_main_forwards_offline_mode_and_user_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = root / "share.tar.gz"
            user_state = SimpleNamespace()

            with patch("engulf_clab_freeze.command.freeze") as mocked_freeze:
                self.assertEqual(
                    main(
                        [
                            "--offline",
                            "--topology",
                            str(topology),
                            "--output",
                            str(archive),
                        ],
                        user_state=user_state,  # type: ignore[arg-type]
                    ),
                    0,
                )

            mocked_freeze.assert_called_once_with(
                topology.resolve(),
                archive.resolve(),
                workspace=None,
                confirm_overwrite=_confirm_overwrite,
                offline=True,
                user_state=user_state,
                application_name="eclab",
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
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
            self.assertEqual(
                yaml.safe_load(topology.read_text(encoding="utf-8")), original
            )
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

    def test_edition_freeze_uses_edition_state_dir_but_fixed_license_marker(
        self,
    ) -> None:
        # The state directory/freezeignore filename stay namespaced by the
        # active application (so every edition's state converges once they
        # share a short_product_name), but the license prompt marker is
        # always the fixed ECLAB label, regardless of application_name.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text(
                "topology: {nodes: {router: {license: '$POOL'}}}\n",
                encoding="utf-8",
            )
            (root / ".vendor_clab" / "cache").mkdir(parents=True)
            (root / ".vendor_clab" / "cache" / "state.json").write_text(
                "private state", encoding="utf-8"
            )
            (root / ".vendor_clab-freezeignore").write_text(
                "omit.txt\n", encoding="utf-8"
            )
            (root / "omit.txt").write_text("omit", encoding="utf-8")
            archive = Path(directory) / "share.tar.gz"
            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze(topology, archive, application_name="vendor clab")
            with tarfile.open(archive, "r:gz") as tar:
                names = tar.getnames()
                frozen = yaml.safe_load(tar.extractfile("share/lab.clab.yml").read())
            self.assertFalse(any(".vendor_clab/cache" in name for name in names))
            self.assertFalse(any(name.endswith("/omit.txt") for name in names))
            self.assertEqual(
                frozen["topology"]["nodes"]["router"]["license"],
                "__ECLAB_LICENSE_PROMPT__",
            )

            (root / ".vendor_clab" / "licenses").mkdir(parents=True)
            with self.assertRaisesRegex(FreezeError, "destroy the lab"):
                freeze(
                    topology,
                    Path(directory) / "other.tar.gz",
                    application_name="vendor clab",
                )

    def test_freeze_rewrites_external_vrnetlab_input_with_fixed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "lab"
            staging = root / "staging"
            source_root.mkdir()
            staging.mkdir()
            source = root / "router.qcow2"
            source.write_bytes(b"image")
            topology_path = source_root / "lab.clab.yml"
            topology = {
                "name": "demo",
                "topology": {
                    "nodes": {
                        "router": {
                            "image": "generated:latest",
                            "env": {
                                "ECLAB_VRNETLAB_TYPE": "vendor/router",
                                "ECLAB_VRNETLAB_IMG_PATH": str(source),
                            },
                        }
                    }
                },
            }
            warnings: list[str] = []
            _copy_external_vrnetlab_inputs(
                topology,
                topology_path,
                source_root,
                staging,
                warnings,
            )
            environment = topology["topology"]["nodes"]["router"]["env"]
            self.assertEqual(
                environment["ECLAB_VRNETLAB_IMG_PATH"],
                "assets/images/router/router.qcow2",
            )

    def test_existing_archive_is_left_unchanged_when_overwrite_is_declined(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = root / "share.tar.gz"
            archive.write_bytes(b"previous archive")

            self.assertFalse(
                freeze(topology, archive, confirm_overwrite=lambda _path: False)
            )
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
                self.assertTrue(
                    freeze(topology, archive, confirm_overwrite=lambda _path: True)
                )

            with tarfile.open(archive, "r:gz") as tar:
                self.assertFalse(
                    any(name.endswith("/share.tar.gz") for name in tar.getnames())
                )

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

    def test_freeze_excludes_runtime_directory_and_prunes_empty_directories(
        self,
    ) -> None:
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
            state = root / "clab-demo"
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
                return any(
                    name == f"share/{path}" or name.startswith(f"share/{path}/")
                    for name in names
                )

            self.assertFalse(archived("clab-demo"))
            self.assertFalse(archived("empty"))
            self.assertFalse(archived("licenses-only"))

    def test_offline_freeze_bundles_components_and_uses_offline_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = Path(directory) / "share.tar.gz"
            user_state = SimpleNamespace()

            with (
                patch("engulf_clab_freeze.command._download_wheels"),
                patch("engulf_clab_freeze.command._bundle_offline_runtime") as runtime,
                patch(
                    "engulf_clab_freeze.command._bundle_offline_containerlab"
                ) as clab,
                patch(
                    "engulf_clab_freeze.command._bundle_offline_vrnetlab",
                    return_value=False,
                ) as vrnetlab,
                patch("engulf_clab_freeze.command._bundle_offline_images") as images,
            ):
                freeze(
                    topology,
                    archive,
                    offline=True,
                    user_state=user_state,  # type: ignore[arg-type]
                )

            runtime.assert_called_once()
            clab.assert_called_once()
            vrnetlab.assert_called_once()
            images.assert_called_once()
            with tarfile.open(archive, "r:gz") as tar:
                launcher = tar.extractfile("share/run-eclab.sh").read().decode()
                frozen = yaml.safe_load(tar.extractfile("share/lab.clab.yml").read())
            self.assertIn('exec "$runtime/bin/python" "$runtime/bin/eclab"', launcher)
            self.assertNotIn("pip install", launcher)
            self.assertTrue(frozen["x-engulf-clab-freeze"]["offline"])


class OfflineBundleTestCase(unittest.TestCase):
    def test_bundles_actual_vrnetlab_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            (checkout / "common").mkdir(parents=True)
            (checkout / "common" / "vrnetlab.py").write_text(
                "# vrnetlab runtime\n", encoding="utf-8"
            )
            builder = checkout / "vendor" / "router"
            builder.mkdir(parents=True)
            (builder / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
            staging = root / "staging"
            staging.mkdir()

            with patch.dict(
                "engulf_clab_freeze.command.os.environ",
                {"VRNETLAB_DIR": str(checkout)},
            ):
                _bundle_offline_vrnetlab(staging)

            bundled = staging / "tools" / "vrnetlab"
            self.assertTrue((bundled / "common" / "vrnetlab.py").is_file())
            self.assertTrue((bundled / "vendor" / "router" / "Makefile").is_file())

    def test_image_references_are_resolved_and_deduplicated(self) -> None:
        topology = {
            "topology": {
                "nodes": {
                    "one": {"image": "${ROUTER_IMAGE}"},
                    "two": {"image": "router:1"},
                    "vm": {
                        "image": "generated-vrnetlab:latest",
                        "env": {"ECLAB_VRNETLAB_TYPE": "vendor/router"},
                    },
                }
            }
        }
        with patch.dict(
            "engulf_clab_freeze.command.os.environ", {"ROUTER_IMAGE": "router:1"}
        ):
            self.assertEqual(_offline_image_references(topology), ("router:1",))
        self.assertEqual(topology["topology"]["nodes"]["one"]["image"], "router:1")

    def test_missing_local_image_makes_offline_freeze_fail(self) -> None:
        topology = {"topology": {"nodes": {"router": {"image": "router:1"}}}}
        with (
            patch(
                "engulf_clab_freeze.command.shutil.which",
                return_value="/usr/bin/docker",
            ),
            patch(
                "engulf_clab_freeze.command.subprocess.run",
                return_value=SimpleNamespace(returncode=1),
            ),
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(FreezeError, "deploy or pull first"),
        ):
            _bundle_offline_images(topology, Path(directory))

    def test_offline_freeze_excludes_vendor_image_but_keeps_vrnetlab_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            source = staging / "router.qcow2"
            source.write_bytes(b"vendor image")
            topology = {
                "name": "demo",
                "topology": {
                    "nodes": {
                        "router": {
                            "image": "generated-vrnetlab:latest",
                            "env": {
                                "ECLAB_VRNETLAB_TYPE": "vendor/router",
                                "ECLAB_VRNETLAB_IMG_PATH": "router.qcow2",
                                "KEEP": "yes",
                            },
                        }
                    }
                },
            }
            warnings: list[str] = []

            _remove_offline_vrnetlab_inputs(
                topology, staging / "lab.clab.yml", staging, warnings
            )

            environment = topology["topology"]["nodes"]["router"]["env"]
            self.assertEqual(
                environment,
                {"ECLAB_VRNETLAB_TYPE": "vendor/router", "KEEP": "yes"},
            )
            self.assertFalse(source.exists())
            self.assertIn(
                "excluded recipient-selected vrnetlab image input", warnings[0]
            )

    def test_offline_launcher_forces_bundled_tools_and_loads_images(self) -> None:
        launcher = _launcher("lab.clab.yml", offline=True)
        self.assertIn('export CONTAINERLAB_BIN="$containerlab"', launcher)
        self.assertIn('export VRNETLAB_DIR="$vrnetlab"', launcher)
        self.assertIn("docker image load --input", launcher)
        self.assertNotIn("pip install", launcher)


class WheelhouseTestCase(unittest.TestCase):
    def test_wheelhouse_seeds_local_wheels_before_downloading_dependencies(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            source = staging / "engulf_clab-0.1.0-py3-none-any.whl"
            source.write_bytes(b"locally-built wheel")
            distribution = SimpleNamespace(
                read_text=lambda name: (
                    json.dumps({"url": source.as_uri()})
                    if name == "direct_url.json"
                    else None
                )
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
            self.assertEqual(
                (wheelhouse / source.name).read_bytes(), source.read_bytes()
            )
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

    def test_empty_incomplete_wheelhouse_is_removed_and_launcher_allows_that(
        self,
    ) -> None:
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


class FreezePrivateEnvironmentTest(unittest.TestCase):
    def test_freeze_resolves_the_env_file_but_leaves_it_out_of_the_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text(
                "name: demo\n"
                "topology:\n"
                "  nodes:\n"
                "    router:\n"
                "      image: $ROUTER_IMAGE\n",
                encoding="utf-8",
            )
            # Sibling env file: resolves the topology, must not travel with it.
            (root / "lab.env").write_text(
                "ROUTER_IMAGE=router:1.0\nAPI_TOKEN=hunter2\n", encoding="utf-8"
            )
            archive = Path(directory) / "share.tar.gz"

            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze(topology, archive)

            with tarfile.open(archive, "r:gz") as tar:
                names = tar.getnames()
                raw = tar.extractfile("share/lab.clab.yml").read().decode()
                frozen = yaml.safe_load(raw)
                notes = tar.extractfile("share/FREEZE-WARNINGS.txt").read().decode()

            self.assertFalse(any(name.endswith("lab.env") for name in names))
            self.assertNotIn("hunter2", raw)
            # The reference stays unresolved on purpose: baking the value in
            # would put private data in an archive meant to be handed on, so
            # the recipient supplies their own env file -- as with licenses.
            self.assertEqual(
                frozen["topology"]["nodes"]["router"]["image"], "$ROUTER_IMAGE"
            )
            self.assertIn("owner-private environment file: lab.env", notes)
