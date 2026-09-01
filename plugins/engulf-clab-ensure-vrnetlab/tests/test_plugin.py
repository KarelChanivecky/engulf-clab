from __future__ import annotations

import tomllib
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_lab_parser import TopologySession, load_topology
from engulf_clab_schema_api import SCHEMA_VRNETLAB_SOURCE_CONTEXT, VrnetlabSourceHint
from engulf_executable_wrapper_api import BeforeCallEvent, CallMode, PreparedCallEvent

from engulf_clab_ensure_vrnetlab.contract import (
    VRNETLAB_PATH_CONTEXT,
    VRNETLAB_REPOSITORY_LEASE,
)
from engulf_clab_ensure_vrnetlab.errors import EnsureVrnetlabError
from engulf_clab_ensure_vrnetlab.plugin import EnsureVrnetlabPlugin


def write_topology(path: Path, *, opted_in: bool) -> None:
    environment = "env: {ECLAB_VRNETLAB_TYPE: vendor/router}" if opted_in else "env: {}"
    path.write_text(
        f"topology:\n  nodes:\n    router:\n      image: router:1\n      {environment}\n",
        encoding="utf-8",
    )


def invocation_api() -> Mock:
    api = Mock(spec=InvocationAPI)
    api.application.display_name = "engulf-clab"
    api.application.product = "Engulf Containerlab"
    api.application.short_product_name = "eclab"
    return api


class PluginLifecycleTest(unittest.TestCase):
    def test_dependencies_are_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_ensure_vrnetlab"
        ]

        self.assertEqual(
            group,
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        self.assertNotIn("plugin_dependencies", EnsureVrnetlabPlugin.__dict__)

    def test_failed_goal_acknowledges_published_source_context(self) -> None:
        plugin = EnsureVrnetlabPlugin()
        api = Mock(spec=AfterGoalAPI)
        invocation = Invocation(("deploy",), Path("/labs"), {})
        result = GoalResult.failed(1, error="earlier plugin failed")

        returned = plugin.after_goal(invocation, result, api)

        self.assertIs(returned, result)
        api.get_context.assert_called_once_with(SCHEMA_VRNETLAB_SOURCE_CONTEXT)

    def test_successful_goal_does_not_claim_an_unconsumed_source(self) -> None:
        plugin = EnsureVrnetlabPlugin()
        api = Mock(spec=AfterGoalAPI)
        result = GoalResult.completed()

        returned = plugin.after_goal(Invocation((), Path("/labs"), {}), result, api)

        self.assertIs(returned, result)
        api.get_context.assert_not_called()

    @patch("engulf_clab_ensure_vrnetlab.plugin.record_plugin_schema")
    @patch("engulf_clab_ensure_vrnetlab.plugin.publish_vrnetlab_source")
    @patch("engulf_clab_ensure_vrnetlab.plugin.vrnetlab_source_hint")
    def test_before_goal_publishes_side_effect_free_selection(
        self,
        select: Mock,
        publish: Mock,
        _record: Mock,
    ) -> None:
        state = object()
        source = VrnetlabSourceHint(
            repository="https://example.test/vrnetlab.git",
            revision="feature",
        )
        select.return_value = source
        api = Mock(spec=BeforeGoalAPI)
        api.state.return_value = state
        invocation = Invocation((), Path("/labs"), {"VRNETLAB_VERSION": "feature"})

        EnsureVrnetlabPlugin().before_goal(invocation, api)

        api.state.assert_called_once_with(StateScope.USER)
        select.assert_called_once_with(state, invocation.environment)
        publish.assert_called_once_with(api, source)

    @patch("engulf_clab_ensure_vrnetlab.plugin.ensure_checkout")
    def test_non_opted_topology_does_not_touch_state(self, ensure: Mock) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            write_topology(topology, opted_in=False)
            api = invocation_api()
            api.lease.return_value = nullcontext()

            EnsureVrnetlabPlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    ("deploy", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                api,
            )

        ensure.assert_not_called()
        api.state.assert_not_called()
        api.set_context.assert_not_called()

    @patch("engulf_clab_ensure_vrnetlab.plugin.publish_vrnetlab_source")
    @patch("engulf_clab_ensure_vrnetlab.plugin.require_vrnetlab_dependencies")
    @patch("engulf_clab_ensure_vrnetlab.plugin.update_vrnetlab")
    @patch("engulf_clab_ensure_vrnetlab.plugin.ensure_checkout")
    def test_opted_topology_publishes_user_checkout(
        self,
        ensure: Mock,
        _update: Mock,
        _dependencies: Mock,
        publish: Mock,
    ) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            write_topology(topology, opted_in=True)
            checkout = Path(directory) / "vrnetlab"
            ensure.return_value = checkout
            state = object()
            api = invocation_api()
            api.lease.return_value = nullcontext()
            api.state.return_value = state
            api.require_context.return_value = TopologySession(topology, load_topology(topology))

            EnsureVrnetlabPlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy", "-t", str(topology)),
                    ("deploy", "-t", str(topology)),
                    CallMode.NORMAL,
                ),
                api,
            )

        api.state.assert_called_once_with(StateScope.USER)
        api.lease.assert_called_once_with(VRNETLAB_REPOSITORY_LEASE)
        self.assertIs(ensure.call_args.args[0], state)
        api.set_context.assert_called_once_with(VRNETLAB_PATH_CONTEXT, str(checkout))
        source = publish.call_args.args[1]
        self.assertEqual(source.checkout, checkout.resolve())
        self.assertTrue(source.resolved)

    @patch(
        "engulf_clab_ensure_vrnetlab.plugin.ensure_checkout",
        side_effect=EnsureVrnetlabError("clone failed"),
    )
    @patch("engulf_clab_ensure_vrnetlab.plugin.require_vrnetlab_dependencies")
    def test_expected_failure_preempts_deploy(self, _dependencies: Mock, _ensure: Mock) -> None:
        with TemporaryDirectory() as directory:
            topology = Path(directory) / "lab.clab.yml"
            write_topology(topology, opted_in=True)
            api = invocation_api()
            api.lease.return_value = nullcontext()
            api.require_context.return_value = TopologySession(topology, load_topology(topology))

            with self.assertRaises(EnsureVrnetlabError):
                EnsureVrnetlabPlugin().prepare_call(
                    PreparedCallEvent(
                        "containerlab",
                        ("deploy", "-t", str(topology)),
                        ("deploy", "-t", str(topology)),
                        CallMode.NORMAL,
                    ),
                    api,
                )

        api.set_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
