from __future__ import annotations

import subprocess
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
from unittest.mock import MagicMock, Mock, call, patch

from engulf_clab_vrnetlab_build_api import VrnetlabSourceProvenanceSnapshot

from engulf_clab_vrnetlab_build.errors import VrnetlabError
from engulf_clab_vrnetlab_build.images import (
    _running_containers_using_image,
    build_native_image,
    ensure_images,
)
from engulf_clab_vrnetlab_build.requests import BuildRequest


def lease_api() -> MagicMock:
    api = MagicMock()
    api.lease.return_value = nullcontext()
    api.leases.return_value = nullcontext()
    return api


class EnsureImagesTest(unittest.TestCase):
    @patch("engulf_clab_vrnetlab_build.images.build_native_image")
    @patch("engulf_clab_vrnetlab_build.images._require_command")
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=False)
    def test_distinct_builders_run_concurrently(
        self,
        image_exists: Mock,
        require_command: Mock,
        build: Mock,
    ) -> None:
        del image_exists, require_command
        rendezvous = Barrier(2)
        build.side_effect = lambda *_args: rendezvous.wait(timeout=2)
        api = lease_api()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            requests: list[BuildRequest] = []
            for node, builder_type in (("r1", "vendor/router"), ("fw1", "vendor/firewall")):
                builder = root / builder_type
                builder.mkdir(parents=True)
                (builder / "Makefile").touch()
                source = root / f"{node}.qcow2"
                source.write_bytes(node.encode())
                requests.append(BuildRequest(node, f"vrnetlab/{node}:1", builder_type, source))

            ensure_images(
                requests,
                api=api,
                checkout_context=root,
                max_workers=2,
            )

        self.assertEqual(build.call_count, 2)
        api.leases.assert_called_once()
        self.assertEqual(
            set(api.leases.call_args.args[0]),
            {
                "docker-image:vrnetlab/r1:1",
                "docker-image:vrnetlab/fw1:1",
                f"vrnetlab-builder:{(root / 'vendor' / 'router').resolve()}",
                f"vrnetlab-builder:{(root / 'vendor' / 'firewall').resolve()}",
            },
        )

    @patch("engulf_clab_vrnetlab_build.images.build_native_image")
    @patch("engulf_clab_vrnetlab_build.images._require_command")
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=False)
    def test_same_builder_runs_serially(
        self,
        image_exists: Mock,
        require_command: Mock,
        build: Mock,
    ) -> None:
        del image_exists, require_command
        active = 0
        peak = 0
        guard = Lock()

        def observe_build(*_args: object) -> None:
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with guard:
                active -= 1

        build.side_effect = observe_build
        api = lease_api()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            (builder / "Makefile").touch()
            requests: list[BuildRequest] = []
            for node in ("r1", "r2"):
                source = root / f"{node}.qcow2"
                source.write_bytes(node.encode())
                requests.append(BuildRequest(node, f"vrnetlab/{node}:1", "vendor/router", source))

            ensure_images(
                requests,
                api=api,
                checkout_context=root,
                max_workers=2,
            )

        self.assertEqual(build.call_count, 2)
        self.assertEqual(peak, 1)
        api.leases.assert_called_once()

    @patch("engulf_clab_vrnetlab_build.images._require_command")
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=True)
    def test_existing_image_without_source_is_used(
        self, image_exists: Mock, require_command: Mock
    ) -> None:
        request = BuildRequest("r1", "vrnetlab/router:1", "vendor/router", None)
        api = lease_api()
        ensure_images(
            [request],
            api=api,
            checkout_context=None,
        )
        image_exists.assert_called_once_with("vrnetlab/router:1")
        require_command.assert_called_once_with("docker")
        api.lease.assert_called_once_with("docker-image:vrnetlab/router:1")

    @patch("engulf_clab_vrnetlab_build.images._require_command")
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=False)
    def test_missing_image_without_source_fails(
        self, image_exists: Mock, require_command: Mock
    ) -> None:
        request = BuildRequest("r1", "vrnetlab/router:1", "vendor/router", None)
        with self.assertRaisesRegex(VrnetlabError, "no vrnetlab provider source resolved"):
            ensure_images(
                [request],
                api=lease_api(),
                checkout_context=None,
            )

    @patch("engulf_clab_vrnetlab_build.images.build_native_image")
    @patch("engulf_clab_vrnetlab_build.images._require_command")
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=True)
    def test_source_backed_request_always_schedules_build(
        self,
        image_exists: Mock,
        require_command: Mock,
        build: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            (builder / "Makefile").touch()
            qcow2 = root / "router-v1.qcow2"
            qcow2.write_bytes(b"qcow")
            request = BuildRequest(
                "r1",
                "vrnetlab/router:1",
                "vendor/router",
                qcow2,
                source_provider_id="org.example.images.static",
            )

            api = lease_api()
            provenance = ensure_images(
                [request],
                api=api,
                checkout_context=root,
            )

        build.assert_called_once()
        image_exists.assert_not_called()
        require_command.assert_has_calls([call("docker"), call("make")])
        self.assertIsInstance(provenance, VrnetlabSourceProvenanceSnapshot)
        self.assertEqual(len(provenance.sources), 1)
        source = provenance.sources[0]
        self.assertEqual(source.node_name, "r1")
        self.assertEqual(source.builder_type, "vendor/router")
        self.assertEqual(source.source_provider_id, "org.example.images.static")
        self.assertEqual(
            source.source_sha256,
            "e60e82356bd75d39a38c0cfd1414f5eddfe226b2ce77d0b3d699619b06e9a90b",
        )
        self.assertFalse(hasattr(source, "image"))
        api.leases.assert_called_once_with(
            ("docker-image:vrnetlab/router:1", f"vrnetlab-builder:{builder.resolve()}")
        )

    @patch("engulf_clab_vrnetlab_build.images.build_native_image")
    @patch("engulf_clab_vrnetlab_build.images._require_command")
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=False)
    def test_conflicting_sources_for_one_tag_fail_before_build(
        self,
        image_exists: Mock,
        require_command: Mock,
        build: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            (builder / "Makefile").touch()
            first = root / "router-v1.qcow2"
            second = root / "router-v2.qcow2"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            requests = [
                BuildRequest("r1", "vrnetlab/router:1", "vendor/router", first),
                BuildRequest("r2", "vrnetlab/router:1", "vendor/router", second),
            ]

            with self.assertRaisesRegex(VrnetlabError, "conflicting"):
                ensure_images(
                    requests,
                    api=lease_api(),
                    checkout_context=root,
                )

        build.assert_not_called()


class NativeBuildTest(unittest.TestCase):
    @patch("engulf_clab_vrnetlab_build.images.subprocess.run")
    def test_running_container_detection_uses_image_ancestor_filter(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["docker"],
            returncode=0,
            stdout="fgt-lab (0123456789ab)\n",
            stderr="",
        )

        containers = _running_containers_using_image("backup:tag")

        self.assertEqual(containers, ("fgt-lab (0123456789ab)",))
        run.assert_called_once_with(
            [
                "docker",
                "container",
                "ls",
                "--filter",
                "ancestor=backup:tag",
                "--format",
                "{{.Names}} ({{.ID}})",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("engulf_clab_vrnetlab_build.images.warning")
    @patch(
        "engulf_clab_vrnetlab_build.images._running_containers_using_image",
        return_value=("fgt-lab (0123456789ab)",),
    )
    @patch("engulf_clab_vrnetlab_build.images._remove_image_tag")
    @patch("engulf_clab_vrnetlab_build.images._restore_target_image")
    @patch(
        "engulf_clab_vrnetlab_build.images._native_image_tag_from_make",
        return_value="vrnetlab/vr-fortios:fortios",
    )
    @patch("engulf_clab_vrnetlab_build.images._protect_target_image", return_value="backup:tag")
    @patch(
        "engulf_clab_vrnetlab_build.images.docker_image_exists",
        side_effect=(False, True),
    )
    @patch("engulf_clab_vrnetlab_build.images._run")
    def test_running_container_keeps_old_tag_and_warns_without_rollback(
        self,
        run: Mock,
        image_exists: Mock,
        protect: Mock,
        native_tag: Mock,
        restore: Mock,
        remove: Mock,
        running: Mock,
        warn: Mock,
    ) -> None:
        del image_exists, protect, native_tag
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "fortinet" / "fortigate"
            builder.mkdir(parents=True)
            source = root / "fortios.qcow2"
            source.write_bytes(b"source")

            build_native_image(source, builder, "vrnetlab/example.fgt:8.0")

        running.assert_called_once_with("backup:tag")
        remove.assert_not_called()
        restore.assert_not_called()
        self.assertEqual(
            run.call_args_list,
            [
                call(["make"], cwd=builder),
                call(
                    [
                        "docker",
                        "tag",
                        "vrnetlab/vr-fortios:fortios",
                        "vrnetlab/example.fgt:8.0",
                    ]
                ),
            ],
        )
        self.assertIn("fgt-lab", warn.call_args.args[0])
        self.assertIn("backup:tag", warn.call_args.args[0])

    @patch("engulf_clab_vrnetlab_build.images.warning")
    @patch(
        "engulf_clab_vrnetlab_build.images._running_containers_using_image",
        return_value=(),
    )
    @patch(
        "engulf_clab_vrnetlab_build.images._remove_image_tag",
        side_effect=subprocess.CalledProcessError(
            1, ["docker", "image", "rm", "backup:tag"], stderr="image is in use"
        ),
    )
    @patch("engulf_clab_vrnetlab_build.images._restore_target_image")
    @patch(
        "engulf_clab_vrnetlab_build.images._native_image_tag_from_make",
        return_value="vrnetlab/vr-fortios:fortios",
    )
    @patch("engulf_clab_vrnetlab_build.images._protect_target_image", return_value="backup:tag")
    @patch(
        "engulf_clab_vrnetlab_build.images.docker_image_exists",
        side_effect=(False, True),
    )
    @patch("engulf_clab_vrnetlab_build.images._run")
    def test_backup_removal_failure_warns_and_keeps_new_image(
        self,
        run: Mock,
        image_exists: Mock,
        protect: Mock,
        native_tag: Mock,
        restore: Mock,
        remove: Mock,
        running: Mock,
        warn: Mock,
    ) -> None:
        del image_exists, protect, native_tag
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "fortinet" / "fortigate"
            builder.mkdir(parents=True)
            source = root / "fortios.qcow2"
            source.write_bytes(b"source")

            build_native_image(source, builder, "vrnetlab/example.fgt:8.0")

        running.assert_called_once_with("backup:tag")
        remove.assert_called_once_with("backup:tag", check=True)
        restore.assert_not_called()
        self.assertIn("image is in use", warn.call_args.args[0])
        self.assertEqual(
            run.call_args_list,
            [
                call(["make"], cwd=builder),
                call(
                    [
                        "docker",
                        "tag",
                        "vrnetlab/vr-fortios:fortios",
                        "vrnetlab/example.fgt:8.0",
                    ]
                ),
            ],
        )

    @patch("engulf_clab_vrnetlab_build.images._protect_target_image", return_value=None)
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=True)
    @patch("engulf_clab_vrnetlab_build.images._run")
    def test_builder_files_are_cleaned_and_restored(
        self, run: Mock, image_exists: Mock, protect: Mock
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            docker_dir = builder / "docker"
            docker_dir.mkdir(parents=True)
            existing = builder / "existing.qcow2"
            existing.write_bytes(b"existing")
            stale = docker_dir / "stale.qcow2.copy"
            stale.write_bytes(b"stale")
            source = root / "router-v1.qcow2"
            source.write_bytes(b"source")

            build_native_image(source, builder, "vrnetlab/router:1")

            self.assertEqual(existing.read_bytes(), b"existing")
            self.assertFalse((builder / source.name).exists())
            self.assertFalse(stale.exists())
            run.assert_called_once_with(["make"], cwd=builder)

    @patch(
        "engulf_clab_vrnetlab_build.images._native_image_tag_from_make",
        return_value="vrnetlab/vr-router:router",
    )
    @patch("engulf_clab_vrnetlab_build.images._protect_target_image", return_value=None)
    @patch(
        "engulf_clab_vrnetlab_build.images.docker_image_exists",
        side_effect=(False, True),
    )
    @patch("engulf_clab_vrnetlab_build.images._run")
    def test_native_image_is_tagged_with_requested_name(
        self,
        run: Mock,
        image_exists: Mock,
        protect: Mock,
        native_tag: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            source = root / "router.qcow2"
            source.write_bytes(b"source")
            requested = "vrnetlab/vendor_router:1.0.0"

            build_native_image(source, builder, requested)

        self.assertEqual(
            run.call_args_list,
            [
                call(["make"], cwd=builder),
                call(
                    [
                        "docker",
                        "tag",
                        "vrnetlab/vr-router:router",
                        requested,
                    ]
                ),
            ],
        )
        self.assertEqual(
            image_exists.call_args_list,
            [call(requested), call("vrnetlab/vr-router:router")],
        )
        protect.assert_called_once_with(requested)
        native_tag.assert_called_once_with(builder)

    @patch(
        "engulf_clab_vrnetlab_build.images._native_image_tag_from_make",
        return_value=None,
    )
    @patch("engulf_clab_vrnetlab_build.images._restore_target_image")
    @patch("engulf_clab_vrnetlab_build.images._protect_target_image", return_value="backup:tag")
    @patch("engulf_clab_vrnetlab_build.images.docker_image_exists", return_value=False)
    @patch("engulf_clab_vrnetlab_build.images._run")
    def test_missing_native_tag_restores_previous_target(
        self,
        run: Mock,
        image_exists: Mock,
        protect: Mock,
        restore: Mock,
        native_tag: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            source = root / "router-v1.qcow2"
            source.write_bytes(b"source")

            with self.assertRaisesRegex(VrnetlabError, "without creating"):
                build_native_image(source, builder, "vrnetlab/router:1")

        restore.assert_called_once_with("backup:tag", "vrnetlab/router:1")
        self.assertEqual(run.call_args_list, [call(["make"], cwd=builder)])
        native_tag.assert_called_once_with(builder)


if __name__ == "__main__":
    unittest.main()
