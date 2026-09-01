from __future__ import annotations

import unittest

from engulf_clab_containers.plugin import ContainersPlugin


class ContainersPluginTest(unittest.TestCase):
    def test_dependencies_are_owned_by_packaging_metadata(self) -> None:
        self.assertNotIn("plugin_dependencies", ContainersPlugin.__dict__)

    def test_prepare_has_no_external_resource_to_unwind(self) -> None:
        self.assertNotIn("prepare_failed", ContainersPlugin.__dict__)


if __name__ == "__main__":
    unittest.main()
