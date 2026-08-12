from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from engulf_clab_freeze.command import FreezeError, freeze


class FreezeCommandTestCase(unittest.TestCase):
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
