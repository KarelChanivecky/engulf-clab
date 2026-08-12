from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_api import InvocationAPI, StateScope
from engulf_clab_lab_parser import TopologySession, load_topology
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

    @patch("engulf_clab_ensure_vrnetlab.plugin.require_vrnetlab_dependencies")
    @patch("engulf_clab_ensure_vrnetlab.plugin.update_vrnetlab")
    @patch("engulf_clab_ensure_vrnetlab.plugin.ensure_checkout")
    def test_opted_topology_publishes_user_checkout(
        self, ensure: Mock, _update: Mock, _dependencies: Mock
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
