from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engulf_clab_vrnetlab_build.errors import VrnetlabError
from engulf_clab_vrnetlab_build.vrnetlab import builder_directory, vrnetlab_root


class CheckoutTest(unittest.TestCase):
    def test_context_path_is_required(self) -> None:
        with TemporaryDirectory() as context_dir:
            self.assertEqual(vrnetlab_root(context_dir), Path(context_dir))
        with self.assertRaisesRegex(VrnetlabError, "does not contain"):
            vrnetlab_root(None)

    def test_builder_requires_safe_vendor_type_and_makefile(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / "vendor" / "router"
            builder.mkdir(parents=True)
            (builder / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")

            self.assertEqual(builder_directory(root, "vendor/router"), builder)
            with self.assertRaises(VrnetlabError):
                builder_directory(root, "vendor/../router")
            with self.assertRaises(VrnetlabError):
                builder_directory(root, "/vendor/router")


if __name__ == "__main__":
    unittest.main()
