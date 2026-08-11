from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, Mock, call, patch

from engulf_clab_vrnetlab.config import BuildRequest
from engulf_clab_vrnetlab.errors import VrnetlabError
from engulf_clab_vrnetlab.images import build_native_image, ensure_images
from engulf_clab_vrnetlab.state import BuildFingerprint, save_state


class MemoryStateStore:
    def __init__(self) -> None:
        self.content: dict[str, str] = {}

    def exists(self, basename: str) -> bool:
        return basename in self.content

    def read_text(self, basename: str) -> str:
        return self.content[basename]

    def write_text(self, basename: str, content: str) -> None:
        self.content[basename] = content

    @contextmanager
    def transaction(self, *, timeout: float | None = None) -> Iterator[MemoryStateStore]:
        del timeout
        yield self


def lease_api() -> MagicMock:
    api = MagicMock()
    api.lease.return_value = nullcontext()
    api.leases.return_value = nullcontext()
    return api


class EnsureImagesTest(unittest.TestCase):
    @patch("engulf_clab_vrnetlab.images._require_command")
    @patch("engulf_clab_vrnetlab.images.docker_image_exists", return_value=True)
    def test_existing_image_without_source_is_used(
        self, image_exists: Mock, require_command: Mock
    ) -> None:
        request = BuildRequest("r1", "vrnetlab/router:1", "vendor/router", None)
        api = lease_api()
        ensure_images(
            [request],
            api=api,
            checkout_context=None,
            state_store=MemoryStateStore(),
        )
        image_exists.assert_called_once_with("vrnetlab/router:1")
        require_command.assert_called_once_with("docker")
        api.lease.assert_called_once_with("docker-image:vrnetlab/router:1")

    @patch("engulf_clab_vrnetlab.images._require_command")
    @patch("engulf_clab_vrnetlab.images.docker_image_exists", return_value=False)
    def test_missing_image_without_source_fails(
        self, image_exists: Mock, require_command: Mock
    ) -> None:
        request = BuildRequest("r1", "vrnetlab/router:1", "vendor/router", None)
        with self.assertRaisesRegex(VrnetlabError, "no ENGULF_CLAB_VRNETLAB_IMG_PATH"):
            ensure_images(
                [request],
                api=lease_api(),
                checkout_context=None,
                state_store=MemoryStateStore(),
            )

    @patch("engulf_clab_vrnetlab.images.build_native_image")
    @patch("engulf_clab_vrnetlab.images.vrnetlab_fingerprint", return_value="git:abc")
    @patch("engulf_clab_vrnetlab.images._require_command")
    @patch("engulf_clab_vrnetlab.images.docker_image_exists", return_value=True)
    def test_matching_fingerprint_skips_build(
        self,
        image_exists: Mock,
        require_command: Mock,
        checkout_fingerprint: Mock,
        build: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            (builder / "Makefile").touch()
            qcow2 = root / "router-v1.qcow2"
            qcow2.write_bytes(b"qcow")
            request = BuildRequest("r1", "vrnetlab/router:1", "vendor/router", qcow2)
            expected = BuildFingerprint(
                qcow2="e60e82356bd75d39a38c0cfd1414f5eddfe226b2ce77d0b3d699619b06e9a90b",
                qcow2_name="router-v1.qcow2",
                vrnetlab="git:abc",
                builder_type="vendor/router",
            )
            store = MemoryStateStore()
            save_state(store, {request.image: expected})

            api = lease_api()
            ensure_images(
                [request],
                api=api,
                checkout_context=root,
                state_store=store,
            )

        build.assert_not_called()
        api.leases.assert_called_once_with(
            ("docker-image:vrnetlab/router:1", f"vrnetlab-builder:{builder.resolve()}")
        )

    @patch("engulf_clab_vrnetlab.images.build_native_image")
    @patch("engulf_clab_vrnetlab.images.vrnetlab_fingerprint", return_value="git:abc")
    @patch("engulf_clab_vrnetlab.images._require_command")
    @patch("engulf_clab_vrnetlab.images.docker_image_exists", return_value=False)
    def test_conflicting_sources_for_one_tag_fail_before_build(
        self,
        image_exists: Mock,
        require_command: Mock,
        checkout_fingerprint: Mock,
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
                    state_store=MemoryStateStore(),
                )

        build.assert_not_called()


class NativeBuildTest(unittest.TestCase):
    @patch("engulf_clab_vrnetlab.images._protect_target_image", return_value=None)
    @patch("engulf_clab_vrnetlab.images.docker_image_exists", return_value=True)
    @patch("engulf_clab_vrnetlab.images._run")
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

    @patch("engulf_clab_vrnetlab.images._restore_target_image")
    @patch("engulf_clab_vrnetlab.images._protect_target_image", return_value="backup:tag")
    @patch("engulf_clab_vrnetlab.images.docker_image_exists", return_value=False)
    @patch("engulf_clab_vrnetlab.images._run")
    def test_missing_native_tag_restores_previous_target(
        self,
        run: Mock,
        image_exists: Mock,
        protect: Mock,
        restore: Mock,
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


if __name__ == "__main__":
    unittest.main()
