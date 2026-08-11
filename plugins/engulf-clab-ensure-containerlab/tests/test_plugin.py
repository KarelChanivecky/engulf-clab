from __future__ import annotations

import os
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI, StateScope
from engulf_executable_wrapper_api import AfterCallEvent, CallMode, PreparedCallEvent

from engulf_clab_ensure_containerlab.containerlab import executable
from engulf_clab_ensure_containerlab.plugin import EnsureContainerlabPlugin


class PluginLifecycleTest(unittest.TestCase):
    @patch("engulf_clab_ensure_containerlab.plugin.ensure_binary")
    def test_prepare_exposes_binary_for_the_wrapped_call(self, ensure: Mock) -> None:
        with TemporaryDirectory() as directory:
            binary = Path(directory) / "containerlab"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            ensure.return_value = binary
            api = Mock(spec=InvocationAPI)
            api.lease.return_value = nullcontext()
            original_path = os.environ.get("PATH", "")
            plugin = EnsureContainerlabPlugin()

            plugin.prepare_call(
                PreparedCallEvent("containerlab", ("version",), ("version",), CallMode.NORMAL),
                api,
            )
            self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], str(binary.parent))
            self.assertTrue(executable(binary))
            plugin.after_call(Mock(spec=AfterCallEvent), api)

        self.assertEqual(os.environ.get("PATH", ""), original_path)
        api.state.assert_called_once_with(StateScope.USER)

    @patch("engulf_clab_ensure_containerlab.plugin.ensure_binary")
    def test_custom_wrapper_binary_is_not_replaced(self, ensure: Mock) -> None:
        plugin = EnsureContainerlabPlugin()
        api = Mock(spec=InvocationAPI)

        plugin.prepare_call(
            PreparedCallEvent("/custom/containerlab", ("version",), ("version",), CallMode.NORMAL),
            api,
        )

        ensure.assert_not_called()
        api.state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
