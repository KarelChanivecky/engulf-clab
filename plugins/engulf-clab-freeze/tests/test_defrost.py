from __future__ import annotations

import io
import json
import os
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import ANY, patch

import yaml
from engulf_clab_freeze.defrost import (
    DefrostError,
    _license_answers,
    defrost,
    destination,
    lease,
    main,
)

FREEZE_KEY = "x-engulf-clab-freeze"


def frozen_topology(
    nodes: dict[str, object], *, offline: bool = False, env_initializer: bool = False
) -> str:
    metadata = {
        "format": 1,
        "application": "engulf-clab",
        "packages": [{"name": "engulf-clab", "version": "0.1.0"}],
        "tools": {"containerlab": None, "vrnetlab": None},
        "licenses": "prompt",
        "offline": offline,
    }
    if env_initializer:
        metadata["env_initializer"] = "initialize-env.sh"
    return yaml.safe_dump(
        {
            "name": "demo",
            "topology": {"nodes": nodes},
            FREEZE_KEY: metadata,
        },
        sort_keys=False,
    )


def build_archive(path: Path, root: str, files: dict[str, str]) -> Path:
    """Write one .tar.gz whose members all live under a single lab root."""
    with tempfile.TemporaryDirectory() as staging:
        lab = Path(staging) / root
        for name, content in files.items():
            member = lab / name
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_text(content, encoding="utf-8")
        with tarfile.open(path, "w:gz") as tar:
            tar.add(lab, arcname=root)
    return path


def image_archive(path: Path, tags: list[str]) -> Path:
    with tempfile.TemporaryDirectory() as staging:
        manifest = Path(staging) / "manifest.json"
        manifest.write_text(json.dumps([{"RepoTags": tags}]), encoding="utf-8")
        with tarfile.open(path, "w") as tar:
            tar.add(manifest, arcname="manifest.json")
    return path


def minimal_lab(license_value: str = "__ECLAB_LICENSE_PROMPT__") -> dict[str, str]:
    return {
        "lab.clab.yml": frozen_topology(
            {"router": {"image": "example/router:1.0.0", "license": license_value}}
        ),
        "requirements.freeze.txt": "engulf-clab==0.1.0\n",
        "run-eclab.sh": "#!/usr/bin/env bash\n",
    }


class DefrostCommandTestCase(unittest.TestCase):
    def test_main_returns_argparse_exit_codes_instead_of_exiting_the_plugin(
        self,
    ) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--help"], program="fclab defrost"), 0)
        self.assertIn("usage: fclab defrost", output.getvalue())

    def test_main_defaults_the_destination_to_the_archive_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "share.tar.gz"
            archive.write_bytes(b"")

            with patch("engulf_clab_freeze.defrost.defrost") as expanded:
                self.assertEqual(main(["share.tar.gz"], cwd=base), 0)

            expanded.assert_called_once_with(
                archive,
                base / "share",
                licenses={},
                prompt_licenses=True,
                prepare_runtime=True,
                select_images=True,
                load_images=False,
                initialize_env=True,
                force=False,
                application_name="eclab",
                logger=None,
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
                user_state=None,
            )

    def test_main_forwards_every_recipient_option(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "share.tgz"
            archive.write_bytes(b"")

            with patch("engulf_clab_freeze.defrost.defrost") as expanded:
                self.assertEqual(
                    main(
                        [
                            "share.tgz",
                            "--into",
                            "labs/demo",
                            "--force",
                            "--license",
                            "router=/pools/site",
                            "--license",
                            "$FALLBACK",
                            "--no-runtime",
                            "--no-images",
                            "--load-images",
                            "--skip-env-init",
                        ],
                        cwd=base,
                    ),
                    0,
                )

            expanded.assert_called_once_with(
                archive,
                base / "labs" / "demo",
                licenses={"router": "/pools/site", "*": "$FALLBACK"},
                prompt_licenses=True,
                prepare_runtime=False,
                select_images=False,
                load_images=True,
                initialize_env=False,
                force=True,
                application_name="eclab",
                logger=None,
                environment=None,
                contributors=ANY,
                contributor_arguments=ANY,
                user_state=None,
            )

    def test_main_reports_failures_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "share.zip").write_bytes(b"")
            self.assertEqual(main(["share.zip"], cwd=base), 1)

    def test_license_answers_separate_node_selections_from_a_shared_one(self) -> None:
        self.assertEqual(
            _license_answers(["router=/pools/a", "/pools/site=b", "$POOL"]),
            {"router": "/pools/a", "*": "$POOL"},
        )


class DefrostTestCase(unittest.TestCase):
    def test_inherited_license_prompts_are_resolved_for_each_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            document = yaml.safe_load(files["lab.clab.yml"])
            document["topology"] = {
                "defaults": {"kind": "linux"},
                "kinds": {"linux": {"license": "__ECLAB_LICENSE_PROMPT__"}},
                "nodes": {"router": {}, "client": {}},
            }
            files["lab.clab.yml"] = yaml.safe_dump(document)
            archive = build_archive(base / "share.tar.gz", "share", files)
            defrost(archive, base / "demo", prepare_runtime=False, prompt_licenses=False, environment={"ECLAB_LICENSE_ROUTER": "$POOL"})
            nodes = yaml.safe_load((base / "demo/lab.clab.yml").read_text())["topology"]["nodes"]
            self.assertEqual(nodes["router"]["license"], "$POOL")
            self.assertEqual(nodes["client"]["license"], "__ECLAB_LICENSE_PROMPT__")

    def test_inherited_archive_selection_is_not_replaced_by_a_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            document = yaml.safe_load(files["lab.clab.yml"])
            document["topology"]["defaults"] = {"kind": "linux"}
            document["topology"]["kinds"] = {"linux": {"env": {"ECLAB_IMAGE_ARCHIVE": "images/chosen.tar"}}}
            files["lab.clab.yml"] = yaml.safe_dump(document)
            archive = build_archive(base / "share.tar.gz", "share", files)
            with patch("engulf_clab_freeze.defrost._bundled_images", return_value={"example/router:1.0.0": base / "demo/images/bundled.tar"}):
                defrost(archive, base / "demo", prepare_runtime=False, prompt_licenses=False, environment={})
            restored = yaml.safe_load((base / "demo/lab.clab.yml").read_text())["topology"]
            self.assertNotIn("ECLAB_IMAGE_ARCHIVE", restored["nodes"]["router"].get("env", {}))
            self.assertEqual(restored["kinds"]["linux"]["env"]["ECLAB_IMAGE_ARCHIVE"], "images/chosen.tar")

    def test_defrost_publishes_a_lab_without_freeze_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files["initialize-env.sh"] = "#!/usr/bin/env bash\n"
            document = yaml.safe_load(files["lab.clab.yml"])
            document[FREEZE_KEY]["env_initializer"] = "initialize-env.sh"
            files["lab.clab.yml"] = yaml.safe_dump(document, sort_keys=False)
            archive = build_archive(base / "share.tar.gz", "share", files)
            pool = base / "pool"
            pool.mkdir()

            self.assertTrue(
                defrost(
                    archive,
                    base / "demo",
                    licenses={"router": str(pool)},
                    prepare_runtime=False,
                )
            )

            lab = base / "demo"
            document = yaml.safe_load(
                (lab / "lab.clab.yml").read_text(encoding="utf-8")
            )
            self.assertNotIn(FREEZE_KEY, document)
            self.assertEqual(
                document["topology"]["nodes"]["router"]["license"], str(pool)
            )
            self.assertEqual((lab / "run-eclab.sh").stat().st_mode & 0o777, 0o755)
            self.assertEqual((lab / "initialize-env.sh").stat().st_mode & 0o777, 0o755)
            record = json.loads(
                (lab / ".eclab-defrost.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["archive"], "share.tar.gz")
            self.assertEqual(record["topology"], "lab.clab.yml")
            self.assertEqual(record["freeze"]["licenses"], "prompt")

    def test_defrost_runs_the_env_initializer_before_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files["initialize-env.sh"] = (
                "#!/usr/bin/env bash\n"
                "printf ran > initializer-ran\n"
            )
            document = yaml.safe_load(files["lab.clab.yml"])
            document[FREEZE_KEY]["env_initializer"] = "initialize-env.sh"
            files["lab.clab.yml"] = yaml.safe_dump(document, sort_keys=False)
            archive = build_archive(base / "share.tar.gz", "share", files)

            defrost(archive, base / "demo", prepare_runtime=False, prompt_licenses=False)

            self.assertEqual((base / "demo/initializer-ran").read_text(), "ran")

    def test_defrost_can_skip_the_env_initializer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files["initialize-env.sh"] = (
                "#!/usr/bin/env bash\n"
                "printf ran > initializer-ran\n"
            )
            document = yaml.safe_load(files["lab.clab.yml"])
            document[FREEZE_KEY]["env_initializer"] = "initialize-env.sh"
            files["lab.clab.yml"] = yaml.safe_dump(document, sort_keys=False)
            archive = build_archive(base / "share.tar.gz", "share", files)

            defrost(
                archive,
                base / "demo",
                initialize_env=False,
                prepare_runtime=False,
                prompt_licenses=False,
            )

            self.assertFalse((base / "demo/initializer-ran").exists())

    def test_defrost_does_not_run_unmarked_legacy_initializer_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files["initialize-env.sh"] = (
                "#!/usr/bin/env bash\n"
                "printf ran > initializer-ran\n"
            )
            archive = build_archive(base / "share.tar.gz", "share", files)

            defrost(archive, base / "demo", prepare_runtime=False, prompt_licenses=False)

            self.assertFalse((base / "demo/initializer-ran").exists())

    def test_defrost_drops_a_legacy_lab_writer_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files[".engulf-clab-lab-stale.clab.yml"] = "topology: {nodes: {}}\n"
            archive = build_archive(base / "share.tar.gz", "share", files)

            defrost(archive, base / "demo", prepare_runtime=False, prompt_licenses=False)

            self.assertFalse((base / "demo/.engulf-clab-lab-stale.clab.yml").exists())

    def test_defrost_resolves_licenses_from_the_environment_before_prompting(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())
            pool = base / "pool"
            pool.mkdir()

            def refuse(node_name: str) -> str | None:
                raise AssertionError(f"prompted for {node_name}")

            defrost(
                archive,
                base / "demo",
                ask=refuse,
                prepare_runtime=False,
                environment={"ECLAB_LICENSE_ROUTER": str(pool)},
            )

            document = yaml.safe_load(
                (base / "demo" / "lab.clab.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                document["topology"]["nodes"]["router"]["license"], str(pool)
            )

    def test_defrost_keeps_the_marker_when_nobody_answers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())

            defrost(
                archive,
                base / "demo",
                ask=lambda node_name: None,
                prepare_runtime=False,
                environment={},
            )

            document = yaml.safe_load(
                (base / "demo" / "lab.clab.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                document["topology"]["nodes"]["router"]["license"],
                "__ECLAB_LICENSE_PROMPT__",
            )

    def test_defrost_rejects_a_license_path_that_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())

            with self.assertRaisesRegex(DefrostError, "license path does not exist"):
                defrost(
                    archive,
                    base / "demo",
                    licenses={"router": str(base / "absent")},
                    prepare_runtime=False,
                )
            self.assertFalse((base / "demo").exists())

    def test_defrost_keeps_a_pool_variable_for_deploy_to_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())

            defrost(
                archive,
                base / "demo",
                licenses={"*": "$PERSONAL_POOL"},
                prepare_runtime=False,
            )

            document = yaml.safe_load(
                (base / "demo" / "lab.clab.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                document["topology"]["nodes"]["router"]["license"], "$PERSONAL_POOL"
            )

    def test_defrost_requires_freeze_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(
                base / "share.tar.gz",
                "share",
                {"lab.clab.yml": "topology: {nodes: {}}\n"},
            )

            with self.assertRaisesRegex(DefrostError, "not a frozen lab archive"):
                defrost(archive, base / "demo", prepare_runtime=False)
            self.assertFalse((base / "demo").exists())

    def test_defrost_rejects_an_unsupported_freeze_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            topology = yaml.safe_dump(
                {"topology": {"nodes": {}}, FREEZE_KEY: {"format": 99}}
            )
            archive = build_archive(
                base / "share.tar.gz", "share", {"lab.clab.yml": topology}
            )

            with self.assertRaisesRegex(DefrostError, "unsupported freeze format"):
                defrost(archive, base / "demo", prepare_runtime=False)

    def test_defrost_rejects_members_escaping_the_archive_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            payload = base / "payload.txt"
            payload.write_text("x", encoding="utf-8")
            archive = base / "share.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(payload, arcname="share/../escaped.txt")

            with self.assertRaisesRegex(DefrostError, "escapes its root"):
                defrost(archive, base / "demo", prepare_runtime=False)
            self.assertFalse((base / "escaped.txt").exists())

    def test_defrost_rejects_several_archive_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            payload = base / "payload.txt"
            payload.write_text("x", encoding="utf-8")
            archive = base / "share.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(payload, arcname="one/lab.clab.yml")
                tar.add(payload, arcname="two/lab.clab.yml")

            with self.assertRaisesRegex(DefrostError, "exactly one lab directory"):
                defrost(archive, base / "demo", prepare_runtime=False)

    def test_defrost_replaces_only_a_recorded_previous_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())
            defrost(
                archive, base / "demo", prepare_runtime=False, prompt_licenses=False
            )

            with self.assertRaisesRegex(DefrostError, "destination already exists"):
                defrost(
                    archive, base / "demo", prepare_runtime=False, prompt_licenses=False
                )

            (base / "demo" / "recipient-notes.txt").write_text("keep", encoding="utf-8")
            defrost(
                archive,
                base / "demo",
                force=True,
                prepare_runtime=False,
                prompt_licenses=False,
            )
            self.assertFalse((base / "demo" / "recipient-notes.txt").exists())

            unrelated = base / "unrelated"
            unrelated.mkdir()
            with self.assertRaisesRegex(DefrostError, "unrecognized directory"):
                defrost(archive, unrelated, force=True, prepare_runtime=False)
            self.assertTrue(unrelated.is_dir())

    def test_defrost_never_replaces_a_destination_created_after_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())
            intruder = base / "demo"

            def create_destination(
                *args: object, **kwargs: object
            ) -> dict[str, object]:
                intruder.mkdir()
                (intruder / "keep.txt").write_text("keep", encoding="utf-8")
                return {"format": 1, "application": "engulf-clab", "offline": False}

            with (
                patch(
                    "engulf_clab_freeze.defrost._freeze_metadata",
                    side_effect=create_destination,
                ),
                self.assertRaises(OSError),
            ):
                defrost(archive, intruder, prepare_runtime=False, prompt_licenses=False)

            self.assertEqual(
                (intruder / "keep.txt").read_text(encoding="utf-8"), "keep"
            )

    def test_defrost_selects_only_bundled_archives_that_carry_the_node_image(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            staging = base / "staging" / "share"
            staging.mkdir(parents=True)
            (staging / "lab.clab.yml").write_text(
                frozen_topology(
                    {
                        "router": {"image": "example/router:1.0.0"},
                        "client": {"image": "example/client:2.0.0"},
                        "vm": {
                            "image": "vrnetlab/vm:1",
                            "env": {"VM_VRNETLAB_TYPE": "generic"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (staging / "images").mkdir()
            image_archive(staging / "images" / "router.tar", ["example/router:1.0.0"])
            image_archive(staging / "images" / "other.tar.gz", ["example/other:9"])
            archive = base / "share.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(staging, arcname="share")

            defrost(archive, base / "demo", prepare_runtime=False, environment={})

            nodes = yaml.safe_load(
                (base / "demo" / "lab.clab.yml").read_text(encoding="utf-8")
            )["topology"]["nodes"]
            self.assertEqual(
                nodes["router"]["env"]["ECLAB_IMAGE_ARCHIVE"], "images/router.tar"
            )
            self.assertIsNone(nodes["client"].get("env"))
            self.assertNotIn("ECLAB_IMAGE_ARCHIVE", nodes["vm"]["env"])

    def test_defrost_uses_the_offline_image_listing_without_reading_the_bundle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files["tools/docker/images.txt"] = "example/router:1.0.0\n"
            files["tools/docker/images.tar"] = "not a real docker save stream"
            archive = build_archive(base / "share.tar.gz", "share", files)

            defrost(
                archive,
                base / "demo",
                prepare_runtime=False,
                prompt_licenses=False,
                environment={},
            )

            nodes = yaml.safe_load(
                (base / "demo" / "lab.clab.yml").read_text(encoding="utf-8")
            )["topology"]["nodes"]
            self.assertEqual(
                nodes["router"]["env"]["ECLAB_IMAGE_ARCHIVE"], "tools/docker/images.tar"
            )

    def test_defrost_keeps_an_image_archive_the_lab_already_declares(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            staging = base / "staging" / "share"
            staging.mkdir(parents=True)
            (staging / "lab.clab.yml").write_text(
                frozen_topology(
                    {
                        "router": {
                            "image": "example/router:1.0.0",
                            "env": {"ECLAB_IMAGE_ARCHIVE": "images/chosen.tar"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (staging / "images").mkdir()
            image_archive(staging / "images" / "other.tar", ["example/router:1.0.0"])
            archive = base / "share.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(staging, arcname="share")

            defrost(archive, base / "demo", prepare_runtime=False, environment={})

            nodes = yaml.safe_load(
                (base / "demo" / "lab.clab.yml").read_text(encoding="utf-8")
            )["topology"]["nodes"]
            self.assertEqual(
                nodes["router"]["env"]["ECLAB_IMAGE_ARCHIVE"], "images/chosen.tar"
            )

    def test_load_images_only_loads_selected_archives_that_docker_lacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            staging = base / "staging" / "share"
            staging.mkdir(parents=True)
            (staging / "lab.clab.yml").write_text(
                frozen_topology({"router": {"image": "example/router:1.0.0"}}),
                encoding="utf-8",
            )
            (staging / "images").mkdir()
            image_archive(staging / "images" / "router.tar", ["example/router:1.0.0"])
            # An unrelated archive no node points at must never reach the daemon.
            image_archive(staging / "images" / "unused.tar", ["example/unused:1"])
            archive = base / "share.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(staging, arcname="share")

            with (
                patch(
                    "engulf_clab_freeze.defrost.shutil.which", return_value="/docker"
                ),
                patch("engulf_clab_freeze.defrost._image_present", return_value=False),
                patch("engulf_clab_freeze.defrost.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                defrost(
                    archive,
                    base / "demo",
                    load_images=True,
                    prepare_runtime=False,
                    environment={},
                )

            run.assert_called_once_with(
                [
                    "docker",
                    "image",
                    "load",
                    "--input",
                    str(base / "demo" / "images" / "router.tar"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_load_images_defers_to_deploy_without_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files["tools/docker/images.txt"] = "example/router:1.0.0\n"
            files["tools/docker/images.tar"] = "stream"
            archive = build_archive(base / "share.tar.gz", "share", files)

            with (
                patch("engulf_clab_freeze.defrost.shutil.which", return_value=None),
                patch("engulf_clab_freeze.defrost.subprocess.run") as run,
            ):
                defrost(
                    archive,
                    base / "demo",
                    load_images=True,
                    prepare_runtime=False,
                    prompt_licenses=False,
                    environment={},
                )

            run.assert_not_called()
            record = json.loads(
                (base / "demo" / ".eclab-defrost.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "docker is unavailable; bundled images stay for deploy to load",
                record["notes"],
            )

    def test_defrost_verifies_and_repoints_a_bundled_offline_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = {
                "lab.clab.yml": frozen_topology(
                    {"router": {"image": "example/router:1.0.0"}}, offline=True
                ),
                "run-eclab.sh": "#!/usr/bin/env bash\n",
                ".eclab-venv/bin/python": "binary",
                ".eclab-venv/bin/eclab": "#!/build/host/.venv/bin/python\nrun()\n",
                "tools/containerlab/bin/containerlab": "binary",
            }
            archive = build_archive(base / "share.tar.gz", "share", files)

            defrost(archive, base / "demo", prompt_licenses=False, environment={})

            launcher = base / "demo" / ".eclab-venv" / "bin" / "eclab"
            self.assertEqual(
                launcher.read_text(encoding="utf-8").splitlines()[0],
                f"#!{base / 'demo' / '.eclab-venv' / 'bin' / 'python'}",
            )
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertTrue(
                os.access(
                    base / "demo" / "tools/containerlab/bin/containerlab", os.X_OK
                )
            )

    def test_defrost_refuses_an_incomplete_offline_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = {
                "lab.clab.yml": frozen_topology({}, offline=True),
                "run-eclab.sh": "#!/usr/bin/env bash\n",
            }
            archive = build_archive(base / "share.tar.gz", "share", files)

            with self.assertRaisesRegex(DefrostError, "complete .eclab-venv runtime"):
                defrost(archive, base / "demo")
            self.assertFalse((base / "demo").exists())

    def test_defrost_reuses_a_matching_installation_instead_of_building_a_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())

            with (
                patch(
                    "engulf_clab_freeze.defrost._installed_packages_match",
                    return_value=True,
                ),
                patch(
                    "engulf_clab_freeze.defrost._create_virtual_environment"
                ) as created,
            ):
                defrost(archive, base / "demo", prompt_licenses=False)

            created.assert_not_called()

    def test_defrost_builds_a_runtime_from_the_wheelhouse_after_publishing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            files["wheelhouse/engulf_clab-0.1.0-py3-none-any.whl"] = "wheel"
            archive = build_archive(base / "share.tar.gz", "share", files)

            with (
                patch(
                    "engulf_clab_freeze.defrost._installed_packages_match",
                    return_value=False,
                ),
                patch(
                    "engulf_clab_freeze.defrost._create_virtual_environment"
                ) as created,
            ):
                defrost(archive, base / "demo", prompt_licenses=False)

            created.assert_called_once()
            venv, requirements, wheelhouse, _notes = created.call_args.args
            self.assertEqual(venv, base / "demo" / ".eclab-venv")
            self.assertEqual(requirements, base / "demo" / "requirements.freeze.txt")
            self.assertEqual(wheelhouse, base / "demo" / "wheelhouse")

    def test_defrost_requires_a_package_lock_before_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = minimal_lab()
            del files["requirements.freeze.txt"]
            archive = build_archive(base / "share.tar.gz", "share", files)

            with self.assertRaisesRegex(DefrostError, "requirements.freeze.txt"):
                defrost(archive, base / "demo", prompt_licenses=False)
            self.assertFalse((base / "demo").exists())

    def test_defrost_rejects_a_destination_whose_parent_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = build_archive(base / "share.tar.gz", "share", minimal_lab())

            with self.assertRaisesRegex(DefrostError, "destination parent"):
                defrost(archive, base / "absent" / "demo", prepare_runtime=False)

    def test_destination_defaults_to_the_sanitized_archive_name(self) -> None:
        base = Path("/labs")
        self.assertEqual(
            destination(Path("/tmp/share lab.tar.gz"), None, base),
            Path("/labs/share-lab"),
        )
        self.assertEqual(
            destination(Path("/tmp/share.tgz"), "demo", base), Path("/labs/demo")
        )

    def test_lease_covers_the_destination_without_parsing_side_effects(self) -> None:
        base = Path("/labs")
        self.assertEqual(lease(["share.tar.gz"], base), "eclab-defrost:/labs/share")
        self.assertEqual(
            lease(["--into", "demo", "share.tar.gz"], base), "eclab-defrost:/labs/demo"
        )
        self.assertEqual(
            lease(["--into=demo", "share.tar.gz"], base), "eclab-defrost:/labs/demo"
        )
        # A flag value is never mistaken for the archive.
        self.assertEqual(
            lease(["--license", "/pools/site", "share.tar.gz"], base),
            "eclab-defrost:/labs/share",
        )
        self.assertEqual(lease(["--help"], base), "eclab-defrost:/labs")


if __name__ == "__main__":
    unittest.main()
