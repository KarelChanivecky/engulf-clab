from __future__ import annotations

import io
import tarfile
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_vrnetlab_build.errors import VrnetlabError
from engulf_clab_vrnetlab_build.sources import file_sha256, prepared_qcow2


class ImageSourceTest(unittest.TestCase):
    def test_direct_qcow2_is_used_without_renaming(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "router-v1.qcow2"
            source.write_bytes(b"qcow")
            with prepared_qcow2(source) as qcow2:
                self.assertEqual(qcow2, source)
                self.assertEqual(file_sha256(qcow2), file_sha256(source))

    def test_zip_extracts_one_nested_qcow2_by_basename(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "router.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("nested/router-v1.qcow2", b"qcow")
                archive.writestr("nested/readme.txt", b"ignored")

            with prepared_qcow2(source) as qcow2:
                self.assertEqual(qcow2.name, "router-v1.qcow2")
                self.assertEqual(qcow2.read_bytes(), b"qcow")

    def test_tar_formats_extract_one_qcow2(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for filename, mode in (
                ("router.tar", "w"),
                ("router.tar.gz", "w:gz"),
                ("router.tgz", "w:gz"),
            ):
                with self.subTest(filename=filename):
                    source = root / filename
                    payload = b"qcow"
                    with tarfile.open(source, mode) as archive:
                        member = tarfile.TarInfo("images/router-v2.qcow2")
                        member.size = len(payload)
                        archive.addfile(member, io.BytesIO(payload))

                    with prepared_qcow2(source) as qcow2:
                        self.assertEqual(qcow2.name, "router-v2.qcow2")
                        self.assertEqual(qcow2.read_bytes(), payload)

    def test_archive_without_qcow2_fails(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "router.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("readme.txt", b"none")
            with self.assertRaisesRegex(VrnetlabError, "exactly one"), prepared_qcow2(source):
                pass

    def test_archive_with_multiple_qcow2_files_fails(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "router.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("one.qcow2", b"one")
                archive.writestr("two.qcow2", b"two")
            with self.assertRaisesRegex(VrnetlabError, "exactly one"), prepared_qcow2(source):
                pass

    def test_unsupported_source_fails(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "router.gz"
            source.write_bytes(b"not-supported")
            with self.assertRaisesRegex(VrnetlabError, "must be"), prepared_qcow2(source):
                pass

    def test_malformed_archive_fails_cleanly(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "router.zip"
            source.write_bytes(b"not-a-zip")
            with (
                self.assertRaisesRegex(VrnetlabError, "invalid zip archive"),
                prepared_qcow2(source),
            ):
                pass


if __name__ == "__main__":
    unittest.main()
