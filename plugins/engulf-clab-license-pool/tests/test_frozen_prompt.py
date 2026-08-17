from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from engulf_api import ApplicationMetadata
from engulf_executable_wrapper_api import HelpAPI

from engulf_clab_license_pool.plugin import (
    LicenseContract,
    LicensePoolPlugin,
    _copy_to_lab,
    _prompt_requests,
    license_contract,
)


class FrozenLicensePromptTestCase(unittest.TestCase):
    def test_help_uses_fixed_prefix_regardless_of_edition(self) -> None:
        api = MagicMock(spec=HelpAPI)
        api.application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="vendor-clab",
            vendor="Example",
            product="Vendor Containerlab",
            short_product_name="vendor clab",
            version="1.0",
        )
        rendered = LicensePoolPlugin().help(api)
        self.assertIn("ECLAB_LIC_CLAMP", rendered)
        self.assertIn("__ECLAB_LICENSE_PROMPT__", rendered)
        self.assertIn("ECLAB_LICENSE[_NODE]", rendered)
        self.assertNotIn("VENDOR_CLAB_LICENSE", rendered)

    def test_contract_splits_fixed_labels_from_dynamic_state_namespace(self) -> None:
        contract = license_contract(
            SimpleNamespace(short_product_name="vendor clab", product="ignored")
        )
        # State stays namespaced by the active short product name...
        self.assertEqual(contract.state_prefix, "VENDOR_CLAB")
        self.assertEqual(contract.state_directory, ".vendor_clab")
        # ...but labels are always the fixed ECLAB prefix, regardless of edition.
        self.assertEqual(contract.prompt_marker, "__ECLAB_LICENSE_PROMPT__")
        self.assertEqual(contract.clamp_environment, "ECLAB_LIC_CLAMP")
        self.assertEqual(contract.license_environment, "ECLAB_LICENSE")

    def test_node_override_accepts_a_direct_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            license_file = Path(directory) / "router.lic"
            license_file.write_text("license", encoding="utf-8")
            pools, direct = _prompt_requests(
                {"topology": {"nodes": {"router-1": {"license": "__ECLAB_LICENSE_PROMPT__"}}}},
                {"ECLAB_LICENSE_ROUTER_1": str(license_file)},
                Path(directory),
                LicenseContract("ECLAB"),
            )
            self.assertEqual(pools, [])
            claim, source = direct["router-1"]
            self.assertTrue(claim.endswith(":router-1"))
            self.assertEqual(source, str(license_file))

    def test_prompt_marker_ignores_state_prefix(self) -> None:
        # LicenseContract's state_prefix only affects state_directory; the
        # prompt marker and env var stay the fixed ECLAB prefix regardless.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            license_file = root / "router.lic"
            license_file.write_text("license", encoding="utf-8")
            pools, direct = _prompt_requests(
                {
                    "topology": {
                        "nodes": {
                            "router-1": {"license": "__ECLAB_LICENSE_PROMPT__"}
                        }
                    }
                },
                {"ECLAB_LICENSE_ROUTER_1": str(license_file)},
                root,
                LicenseContract("VENDOR_CLAB"),
            )
            self.assertEqual(pools, [])
            self.assertEqual(direct["router-1"][1], str(license_file))

    def test_generated_license_state_uses_the_state_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "router.lic"
            source.write_text("license", encoding="utf-8")
            copied = _copy_to_lab(
                source, root, "claim", LicenseContract("VENDOR_CLAB")
            )
            self.assertEqual(copied.parts[-4], ".vendor_clab")
            self.assertTrue(copied.is_file())
