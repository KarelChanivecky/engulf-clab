from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import chdir, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

import pytest
import yaml
from engulf_clab_freeze.command import (
    FreezeError,
    _bundle_offline_vrnetlab,
    _confirm_overwrite,
    _download_wheels,
    _environment_initializer_script,
    _environment_references,
    _launcher,
    _write_self_extracting_archive,
    freeze,
    main,
)


def _open_self_extracting_archive(path: Path) -> tarfile.TarFile:
    data = path.read_bytes()
    marker = b"__ECLAB_ARCHIVE_BELOW__\n"
    payload_offset = data.index(marker) + len(marker)
    return tarfile.open(fileobj=io.BytesIO(data[payload_offset:]), mode="r:gz")


@pytest.fixture(autouse=True)
def no_image_host_work(monkeypatch):
    monkeypatch.setattr(
        "engulf_clab_freeze.images.inspect_image", lambda _reference: None
    )
    monkeypatch.setattr(
        "engulf_clab_freeze.images.registry_identity",
        lambda _reference, _local: "sha256:" + "a" * 64,
    )


class FreezeCommandTestCase(unittest.TestCase):
    def test_freeze_rejects_incompatible_runtime_modes_before_touching_lab(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            with self.assertRaisesRegex(FreezeError, "cannot be combined"):
                freeze(
                    topology, root / "archive.tar.gz", offline=True, with_runtime=True
                )
            self.assertFalse((root / "archive.tar.gz").exists())

    def test_empty_environment_initializer_is_silent(self) -> None:
        script = _environment_initializer_script("lab.env", [])

        self.assertNotIn(
            "no topology environment values need initialization.",
            script,
        )

    def test_environment_reference_discovery_matches_supported_forms(self) -> None:
        self.assertEqual(
            _environment_references(
                "$IMAGE ${DEFAULT_IMAGE:-$FALLBACK_IMAGE} $$LITERAL $5"
            ),
            {"IMAGE", "DEFAULT_IMAGE", "FALLBACK_IMAGE"},
        )

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
                with_runtime=False,
                external_images=(),
                bundle_images=(),
                user_state=None,
                application_name="eclab",
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
                requirements=(),
            )

    def test_main_defaults_runtime_bundle_to_self_extracting_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            with (
                patch("engulf_clab_freeze.command.freeze") as mocked_freeze,
                patch("engulf_clab_lab_parser.session.Path.cwd", return_value=root),
            ):
                self.assertEqual(main(["--eclab-with-runtime"]), 0)

            self.assertEqual(
                mocked_freeze.call_args.args[:2],
                (topology.resolve(), root / f"{root.name}.run"),
            )
            self.assertTrue(mocked_freeze.call_args.kwargs["with_runtime"])

    def test_main_defaults_offline_package_to_self_extracting_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            with (
                patch("engulf_clab_freeze.command.freeze") as mocked_freeze,
                patch("engulf_clab_lab_parser.session.Path.cwd", return_value=root),
            ):
                self.assertEqual(main(["--eclab-offline"]), 0)

            self.assertEqual(
                mocked_freeze.call_args.args[:2],
                (topology.resolve(), root / f"{root.name}.run"),
            )
            self.assertTrue(mocked_freeze.call_args.kwargs["offline"])

    def test_self_extracting_archive_runs_defrost_to_default_and_custom_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "content"
            content.mkdir()
            (content / "defrost.sh").write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                '[ "$1" = --eclab-output ]\n'
                "output=$2\n"
                "shift 2\n"
                'mkdir -p -- "$output"\n'
                "printf '%s\\n' ran > \"$output/defrost-ran\"\n"
                'if [ "$#" -gt 0 ]; then\n'
                '  printf \'%s\\n\' "$@" > "$output/forwarded-args"\n'
                "else\n"
                '  : > "$output/forwarded-args"\n'
                "fi\n",
                encoding="utf-8",
            )
            (content / "defrost.sh").chmod(0o755)
            payload = root / "payload.tar.gz"
            with tarfile.open(payload, "w:gz") as tar:
                tar.add(content / "defrost.sh", arcname="defrost.sh")
            package = root / "runtime-package.run"
            _write_self_extracting_archive(package, payload, package.name)
            minimal_path = root / "minimal-path"
            minimal_path.mkdir()
            for tool in (
                "basename",
                "dirname",
                "gzip",
                "mkdir",
                "mktemp",
                "mv",
                "rm",
                "tail",
                "tar",
            ):
                executable = shutil.which(tool)
                self.assertIsNotNone(executable)
                (minimal_path / tool).symlink_to(executable)

            default = subprocess.run(
                [str(package)],
                cwd=root,
                env={"PATH": str(minimal_path)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(default.returncode, 0, default.stderr)
            self.assertTrue((root / "runtime-package" / "defrost-ran").is_file())
            self.assertEqual(
                (root / "runtime-package" / "forwarded-args").read_text(), ""
            )
            self.assertEqual(list(root.glob(".runtime-package.extract.*")), [])

            custom = root / "custom output"
            selected = subprocess.run(
                [
                    str(package),
                    "--eclab-output",
                    str(custom),
                    "--eclab-license",
                    "router=/pool",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertTrue((custom / "defrost-ran").is_file())
            self.assertEqual(
                (custom / "forwarded-args").read_text(),
                "--eclab-license\nrouter=/pool\n",
            )
            self.assertEqual(list(root.glob(".custom output.extract.*")), [])

            conflict = subprocess.run(
                [str(package), "--eclab-output", str(custom)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("already exists", conflict.stderr)

    def test_main_accepts_an_explicit_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = root / "share.tar.gz"

            with patch("engulf_clab_freeze.command.freeze") as mocked_freeze:
                self.assertEqual(
                    main(
                        [
                            "--eclab-topology",
                            str(topology),
                            "--eclab-output",
                            str(archive),
                        ]
                    ),
                    0,
                )

            mocked_freeze.assert_called_once_with(
                topology.resolve(),
                archive.resolve(),
                workspace=None,
                confirm_overwrite=_confirm_overwrite,
                offline=False,
                with_runtime=False,
                external_images=(),
                bundle_images=(),
                user_state=None,
                application_name="eclab",
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
                requirements=(),
            )

    def test_main_selects_topology_from_positional_lab_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")

            with (
                chdir(directory),
                patch("engulf_clab_freeze.command.freeze") as mocked_freeze,
            ):
                self.assertEqual(main(["lab"]), 0)

            self.assertEqual(
                mocked_freeze.call_args.args[:2],
                (topology.resolve(), Path(directory) / "lab.tar.gz"),
            )

    def test_main_rejects_directory_with_explicit_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("engulf_clab_freeze.command.freeze") as mocked_freeze:
                self.assertEqual(main([directory, "-t", "lab.clab.yml"]), 2)
            mocked_freeze.assert_not_called()

    def test_main_rejects_unscoped_freeze_flags(self) -> None:
        for args in (
            ["--output", "share.tar.gz"],
            ["--offline"],
            ["--external-image", "example/router:1"],
            ["--bundle-image", "example/router:1"],
            ["--topology", "lab.clab.yml"],
        ):
            with (
                self.subTest(args=args),
                patch("engulf_clab_freeze.command.freeze") as mocked_freeze,
            ):
                self.assertEqual(main(args), 2)
                mocked_freeze.assert_not_called()

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
                            "--eclab-offline",
                            "--eclab-topology",
                            str(topology),
                            "--eclab-output",
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
                with_runtime=False,
                external_images=(),
                bundle_images=(),
                user_state=user_state,
                application_name="eclab",
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
                requirements=(),
            )

    def test_freeze_sanitizes_a_copy_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            original = {
                "name": "demo",
                "topology": {
                    "defaults": {
                        "license": "/private/default.lic",
                        "env": {"ECLAB_LIC_CLAMP": "default.lic"},
                    },
                    "kinds": {
                        "unused": {
                            "license": "/private/kind.lic",
                            "env": {"ECLAB_LIC_CLAMP": "kind.lic"},
                        }
                    },
                    "groups": {
                        "unused": {
                            "license": "/private/group.lic",
                            "env": {"ECLAB_LIC_CLAMP": "group.lic"},
                        }
                    },
                    "nodes": {
                        "router": {
                            "license": "$PERSONAL_POOL",
                            "env": {"ECLAB_LIC_CLAMP": "personal.lic", "KEEP": "yes"},
                        }
                    },
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
                metadata = json.load(tar.extractfile("share/freeze.json"))["freeze"]
            router = frozen["topology"]["nodes"]["router"]
            self.assertEqual(router["license"], "__ECLAB_LICENSE_PROMPT__")
            self.assertNotIn("ECLAB_LIC_CLAMP", router["env"])
            self.assertEqual(router["env"]["KEEP"], "yes")
            for definition in (
                frozen["topology"]["defaults"],
                frozen["topology"]["kinds"]["unused"],
                frozen["topology"]["groups"]["unused"],
            ):
                self.assertEqual(definition["license"], "__ECLAB_LICENSE_PROMPT__")
                self.assertNotIn("ECLAB_LIC_CLAMP", definition["env"])
            self.assertNotIn("x-engulf-clab-freeze", frozen)
            self.assertEqual(metadata["licenses"], "prompt")
            self.assertEqual(
                metadata["env_initializer"],
                "initialize-env.sh",
            )

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
            with patch("engulf_clab_freeze.command.runtime_provider") as provider:
                from engulf_clab_freeze.runtime import EclabRuntimeProvider

                provider.return_value = EclabRuntimeProvider()
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
            with patch("engulf_clab_freeze.command.runtime_provider") as provider:
                from engulf_clab_freeze.runtime import EclabRuntimeProvider

                provider.return_value = EclabRuntimeProvider()
                with self.assertRaisesRegex(FreezeError, "destroy the lab"):
                    freeze(
                        topology,
                        Path(directory) / "other.tar.gz",
                        application_name="vendor clab",
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

    def test_freeze_excludes_the_lab_writer_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            generated = root / ".engulf-clab-lab-generated.clab.yml"
            generated.write_text("topology: {nodes: {stale: {}}}\n", encoding="utf-8")
            archive = Path(directory) / "share.tar.gz"

            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze(topology, archive)

            with tarfile.open(archive, "r:gz") as tar:
                names = tar.getnames()

            self.assertIn("share/lab.clab.yml", names)
            self.assertNotIn("share/.engulf-clab-lab-generated.clab.yml", names)

    def test_offline_freeze_bundles_components_and_uses_offline_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text("topology: {nodes: {}}\n", encoding="utf-8")
            archive = Path(directory) / "share.run"
            user_state = SimpleNamespace()

            def bundle_venv(staging, edition):
                binaries = staging / ".eclab-venv" / "bin"
                binaries.mkdir(parents=True)
                for binary in ("python", edition):
                    (binaries / binary).write_text("#!/bin/sh\nexit 0\n")
                    (binaries / binary).chmod(0o755)

            with (
                patch(
                    "engulf_clab_freeze.runtime.EclabRuntimeProvider.capture",
                    return_value={
                        "containerlab": {"version": "1", "commit": "a"},
                        "vrnetlab": {"revision": "a"},
                    },
                ),
                patch(
                    "engulf_clab_freeze.runtime._tool_paths",
                    return_value=(Path("/bin/clab"), Path("/vrnetlab")),
                ),
                patch(
                    "engulf_clab_freeze.runtime._containerlab_version",
                    return_value={"version": "1", "commit": "a"},
                ),
                patch(
                    "engulf_clab_freeze.runtime._git_identity",
                    return_value={"revision": "a"},
                ),
                patch("engulf_clab_freeze.command._download_wheels"),
                patch(
                    "engulf_clab_freeze.command._bundle_offline_runtime",
                    side_effect=bundle_venv,
                ) as runtime,
                patch(
                    "engulf_clab_freeze.command._bundle_offline_containerlab"
                ) as clab,
                patch(
                    "engulf_clab_freeze.command._bundle_offline_vrnetlab",
                    side_effect=lambda staging, *_: (
                        staging / "tools" / "vrnetlab"
                    ).mkdir(parents=True),
                ) as vrnetlab,
                patch(
                    "engulf_clab_freeze.command.freeze_images", return_value={}
                ) as images,
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
            with _open_self_extracting_archive(archive) as tar:
                self.assertIn("runtime/.eclab-venv/bin/eclab", tar.getnames())
                defroster = tar.extractfile("defrost.sh").read().decode()
                inner_data = tar.extractfile("lab.tgz").read()
            with tarfile.open(fileobj=io.BytesIO(inner_data), mode="r:gz") as tar:
                inner_names = tar.getnames()
                launcher = tar.extractfile("share/run-eclab.sh").read().decode()
                frozen = yaml.safe_load(tar.extractfile("share/lab.clab.yml").read())
                metadata = json.load(tar.extractfile("share/freeze.json"))["freeze"]
                revision = tar.extractfile(
                    "share/tools/vrnetlab/.eclab-freeze-revision"
                ).read()
            self.assertEqual(revision, b"a\n")
            self.assertIn('defrost "$root/lab.tgz"', defroster)
            self.assertIn("ECLAB_FREEZE_RUNTIME", defroster)
            self.assertFalse(any("/.eclab-venv/" in name for name in inner_names))
            self.assertIn('exec "$runtime/bin/python" "$runtime/bin/eclab"', launcher)
            self.assertNotIn("pip install", launcher)
            self.assertNotIn("x-engulf-clab-freeze", frozen)
            self.assertTrue(metadata["offline"])


class OfflineBundleTestCase(unittest.TestCase):
    def test_bundles_actual_vrnetlab_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
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
            self.assertTrue((bundled / ".git").is_file())
            status = subprocess.run(
                ["git", "-C", str(bundled), "status", "--short"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(status.returncode, 0)
            self.assertEqual(status.stdout, "")

    def test_offline_launcher_forces_bundled_tools_and_leaves_images_to_provider(
        self,
    ) -> None:
        launcher = _launcher("lab.clab.yml", offline=True)
        self.assertIn('export CONTAINERLAB_BIN="$containerlab"', launcher)
        self.assertIn('export VRNETLAB_DIR="$vrnetlab"', launcher)
        self.assertIn("unset CONTAINERLAB_VERSION VRNETLAB_VERSION", launcher)
        self.assertNotIn("docker image load", launcher)
        self.assertNotIn("pip install", launcher)

    def test_runtime_launcher_can_prepare_the_venv_without_deploying(self) -> None:
        launcher = _launcher("lab.clab.yml")

        self.assertIn('"${1-}" == --eclab-build-venv', launcher)
        self.assertIn('"$prepare_only" -eq 1', launcher)
        self.assertIn('echo "prepared .eclab-venv"', launcher)


class WheelhouseTestCase(unittest.TestCase):
    def test_wheelhouse_seeds_local_wheels_before_downloading_dependencies(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            source = staging / "engulf_clab-0.1.0-py3-none-any.whl"
            source.write_bytes(b"locally-built wheel")
            local = SimpleNamespace(
                read_text=lambda name: (
                    json.dumps({"url": source.as_uri()})
                    if name == "direct_url.json"
                    else None
                )
            )
            indexed = SimpleNamespace(read_text=lambda _name: None)
            warnings: list[str] = []
            with (
                patch(
                    "engulf_clab_freeze.command.importlib.metadata.distribution",
                    side_effect=lambda name: (
                        local if name == "engulf-clab" else indexed
                    ),
                ),
                patch(
                    "engulf_clab_freeze.command.subprocess.run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
            ):
                self.assertTrue(
                    _download_wheels(
                        staging,
                        [("engulf-clab", "0.1.0"), ("PyYAML", "6.0")],
                        warnings,
                    )
                )

            wheelhouse = staging / "wheelhouse"
            self.assertEqual(
                (wheelhouse / source.name).read_bytes(), source.read_bytes()
            )
            self.assertEqual(warnings, [])
            command = run.call_args.args[0]
            self.assertIn("--no-deps", command)
            self.assertNotIn("--find-links", command)
            self.assertFalse((staging / "requirements.missing.txt").exists())

    def test_seeded_packages_are_never_replaced_from_an_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            source = staging / "engulf_clab-0.1.0-py3-none-any.whl"
            source.write_bytes(b"locally-built wheel")
            distribution = SimpleNamespace(
                read_text=lambda _name: json.dumps({"url": source.as_uri()})
            )
            with (
                patch(
                    "engulf_clab_freeze.command.importlib.metadata.distribution",
                    return_value=distribution,
                ),
                patch("engulf_clab_freeze.command.subprocess.run") as run,
            ):
                self.assertTrue(
                    _download_wheels(staging, [("engulf-clab", "0.1.0")], [])
                )
            run.assert_not_called()

    def test_incomplete_download_keeps_seeded_wheels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            source = staging / "engulf_clab-0.1.0-py3-none-any.whl"
            source.write_bytes(b"locally-built wheel")
            local = SimpleNamespace(
                read_text=lambda _name: json.dumps({"url": source.as_uri()})
            )
            indexed = SimpleNamespace(read_text=lambda _name: None)
            warnings: list[str] = []
            with (
                patch(
                    "engulf_clab_freeze.command.importlib.metadata.distribution",
                    side_effect=lambda name: (
                        local if name == "engulf-clab" else indexed
                    ),
                ),
                patch(
                    "engulf_clab_freeze.command.subprocess.run",
                    return_value=SimpleNamespace(returncode=1),
                ),
            ):
                _download_wheels(
                    staging, [("engulf-clab", "0.1.0"), ("pyyaml", "6.0")], warnings
                )

            self.assertTrue((staging / "wheelhouse" / source.name).is_file())
            self.assertEqual(
                warnings,
                [
                    "could not obtain a complete wheelhouse; launcher will fall back to its package index"
                ],
            )

    def test_installed_pure_package_is_repacked_from_its_files(self) -> None:
        import importlib.metadata
        import zipfile

        from engulf_clab_freeze.command import _repack_installed_wheel

        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"
            (site / "demo").mkdir(parents=True)
            (site / "demo" / "__init__.py").write_text("VALUE = 1\n")
            (site / "demo" / "__pycache__").mkdir()
            (site / "demo" / "__pycache__" / "x.pyc").write_bytes(b"cache")
            info = site / "demo_pkg-1.0.dist-info"
            info.mkdir()
            (info / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: demo-pkg\nVersion: 1.0\n"
            )
            (info / "WHEEL").write_text(
                "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            )
            (info / "entry_points.txt").write_text(
                "[console_scripts]\ndemo = demo:main\n"
            )
            (info / "INSTALLER").write_text("pip\n")
            (info / "RECORD").write_text(
                "demo/__init__.py,,\ndemo/__pycache__/x.pyc,,\n"
                "demo_pkg-1.0.dist-info/METADATA,,\ndemo_pkg-1.0.dist-info/WHEEL,,\n"
                "demo_pkg-1.0.dist-info/entry_points.txt,,\n"
                "demo_pkg-1.0.dist-info/INSTALLER,,\ndemo_pkg-1.0.dist-info/RECORD,,\n"
                "../../bin/demo,,\n"
            )
            wheelhouse = Path(directory) / "wheelhouse"
            wheelhouse.mkdir()
            distribution = importlib.metadata.PathDistribution(info)

            self.assertTrue(_repack_installed_wheel(distribution, wheelhouse))

            with zipfile.ZipFile(wheelhouse / "demo_pkg-1.0-py3-none-any.whl") as wheel:
                names = sorted(wheel.namelist())
                record = wheel.read("demo_pkg-1.0.dist-info/RECORD").decode()
            self.assertEqual(
                names,
                [
                    "demo/__init__.py",
                    "demo_pkg-1.0.dist-info/METADATA",
                    "demo_pkg-1.0.dist-info/RECORD",
                    "demo_pkg-1.0.dist-info/WHEEL",
                    "demo_pkg-1.0.dist-info/entry_points.txt",
                ],
            )
            self.assertIn("demo/__init__.py,sha256=", record)

            (info / "RECORD").write_text("demo/__init__.py,,\n../../share/data.txt,,\n")
            self.assertFalse(
                _repack_installed_wheel(
                    importlib.metadata.PathDistribution(info), wheelhouse
                )
            )

    def test_editable_install_is_built_from_its_live_source(self) -> None:
        from engulf_clab_freeze.command import _seed_installed_wheels

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
            distribution = SimpleNamespace(
                read_text=lambda _name: json.dumps(
                    {"url": project.as_uri(), "dir_info": {"editable": True}}
                )
            )
            wheelhouse = Path(directory) / "wheelhouse"
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
                _seed_installed_wheels([("demo", "1")], wheelhouse, [])
            command = run.call_args.args[0]
            self.assertEqual(command[3:5], ["wheel", "--no-deps"])
            self.assertEqual(command[-1], str(project))

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
            self.assertIn('--find-links "$wheelhouse"', _launcher("lab.clab.yml"))


class FreezePrivateEnvironmentTest(unittest.TestCase):
    def test_environment_initializer_uses_exported_values_without_prompting(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initializer = root / "initialize-env.sh"
            initializer.write_text(
                _environment_initializer_script("lab.env", ["API_TOKEN"]),
                encoding="utf-8",
            )
            initializer.chmod(0o755)

            completed = subprocess.run(
                [str(initializer)],
                env={**os.environ, "API_TOKEN": "secret=value"},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("FREEZE-README.md", completed.stdout)
            self.assertEqual(
                (root / "lab.env").read_text(encoding="utf-8"),
                'API_TOKEN="secret=value"\n',
            )

    def test_freeze_adds_a_recipient_env_initializer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lab"
            root.mkdir()
            topology = root / "lab.clab.yml"
            topology.write_text(
                "name: demo\n"
                "topology:\n"
                "  nodes:\n"
                "    router:\n"
                "      image: $ROUTER_IMAGE\n"
                "      env:\n"
                "        API_TOKEN: $API_TOKEN\n"
                "        LITERAL: $$NOT_AN_INPUT\n",
                encoding="utf-8",
            )
            (root / "lab.env").write_text("API_TOKEN=hunter2\n", encoding="utf-8")
            archive = Path(directory) / "share.tar.gz"

            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze(topology, archive)

            with tarfile.open(archive, "r:gz") as tar:
                names = tar.getnames()
                script = tar.extractfile("share/initialize-env.sh").read()

            recipient = Path(directory) / "recipient"
            recipient.mkdir()
            initializer = recipient / "initialize-env.sh"
            initializer.write_bytes(script)
            initializer.chmod(0o755)
            completed = subprocess.run(
                [str(initializer)],
                input="\nrouter:1\n",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("FREEZE-README.md", completed.stdout)
            self.assertIn("Value for ROUTER_IMAGE", completed.stdout)
            self.assertIn("Left API_TOKEN unset.", completed.stdout)
            self.assertNotIn(
                "no topology environment values need initialization.",
                completed.stdout,
            )
            self.assertEqual(
                (recipient / "lab.env").read_text(encoding="utf-8"),
                'ROUTER_IMAGE="router:1"\n',
            )
            self.assertEqual((recipient / "lab.env").stat().st_mode & 0o777, 0o600)
            self.assertIn("API_TOKEN", script.decode())
            self.assertNotIn("NOT_AN_INPUT", script.decode())
            self.assertNotIn("hunter2", script.decode())
            self.assertNotIn("share/lab.env", names)

    def test_freeze_resolves_the_env_file_but_leaves_it_out_of_the_archive(
        self,
    ) -> None:
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
