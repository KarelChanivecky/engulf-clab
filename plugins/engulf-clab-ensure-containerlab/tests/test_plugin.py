from __future__ import annotations

import os
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import BeforeGoalAPI, GoalResultStatus, Invocation, InvocationAPI, StateScope
from engulf_clab_schema_api import ContainerlabSourceHint, ContainerlabSourceKind
from engulf_executable_wrapper_api import AfterCallEvent, CallMode, PreparedCallEvent

from engulf_clab_ensure_containerlab.containerlab import executable
from engulf_clab_ensure_containerlab.plugin import EnsureContainerlabPlugin


class PluginLifecycleTest(unittest.TestCase):
    @patch("engulf_clab_ensure_containerlab.plugin.record_plugin_schema")
    @patch("engulf_clab_ensure_containerlab.plugin.publish_containerlab_source")
    @patch("engulf_clab_ensure_containerlab.plugin.enable_sudoless")
    @patch("engulf_clab_ensure_containerlab.plugin.ensure_binary")
    @patch("engulf_clab_ensure_containerlab.plugin.sudoless_user", return_value="alice")
    def test_sudoless_preempts_the_wrapped_goal(
        self,
        _user: Mock,
        ensure: Mock,
        enable: Mock,
        publish: Mock,
        _record: Mock,
    ) -> None:
        binary = Path("/usr/local/bin/containerlab")
        ensure.return_value = binary
        api = Mock(spec=BeforeGoalAPI)
        api.lease.return_value = nullcontext()
        state = object()
        api.state.return_value = state
        invocation = Invocation(("sudoless",), Path("/labs"), {})

        result = EnsureContainerlabPlugin().before_goal(invocation, api)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        ensure.assert_called_once_with(state, invocation.environment)
        enable.assert_called_once_with(binary, "alice")
        api.lease.assert_called_once_with("repository-cache:containerlab")
        publish.assert_called_once()

    @patch("engulf_clab_ensure_containerlab.plugin.record_plugin_schema")
    @patch("engulf_clab_ensure_containerlab.plugin.publish_containerlab_source")
    @patch("engulf_clab_ensure_containerlab.plugin.containerlab_source_hint")
    def test_before_goal_publishes_side_effect_free_selection(
        self,
        select: Mock,
        publish: Mock,
        _record: Mock,
    ) -> None:
        state = object()
        source = ContainerlabSourceHint(
            ContainerlabSourceKind.REPOSITORY,
            repository="https://example.test/containerlab.git",
            revision="feature",
        )
        select.return_value = source
        api = Mock(spec=BeforeGoalAPI)
        api.state.return_value = state
        invocation = Invocation((), Path("/labs"), {"CONTAINERLAB_VERSION": "feature"})

        EnsureContainerlabPlugin().before_goal(invocation, api)

        api.state.assert_called_once_with(StateScope.USER)
        select.assert_called_once_with(state, invocation.environment)
        publish.assert_called_once_with(api, source)

    @patch("engulf_clab_ensure_containerlab.plugin.publish_containerlab_source")
    @patch("engulf_clab_ensure_containerlab.plugin.require_containerlab_dependencies")
    @patch("engulf_clab_ensure_containerlab.plugin.ensure_binary")
    def test_prepare_exposes_binary_for_the_wrapped_call(
        self,
        ensure: Mock,
        _dependencies: Mock,
        publish: Mock,
    ) -> None:
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
        published = publish.call_args.args[1]
        self.assertIs(published.kind, ContainerlabSourceKind.BINARY)
        self.assertTrue(published.resolved)

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
