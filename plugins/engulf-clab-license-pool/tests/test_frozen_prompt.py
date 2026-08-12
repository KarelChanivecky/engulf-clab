from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_clab_license_pool.plugin import _prompt_requests


class FrozenLicensePromptTestCase(unittest.TestCase):
    def test_node_override_accepts_a_direct_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            license_file = Path(directory) / "router.lic"
            license_file.write_text("license", encoding="utf-8")
            pools, direct = _prompt_requests(
                {"topology": {"nodes": {"router-1": {"license": "__ECLAB_LICENSE_PROMPT__"}}}},
                {"ECLAB_LICENSE_ROUTER_1": str(license_file)},
                Path(directory),
            )
            self.assertEqual(pools, [])
            claim, source = direct["router-1"]
            self.assertTrue(claim.endswith(":router-1"))
            self.assertEqual(source, str(license_file))
