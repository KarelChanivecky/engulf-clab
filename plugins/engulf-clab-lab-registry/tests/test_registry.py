from __future__ import annotations

import json
import tomllib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import MagicMock, patch

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    StateStore,
)
from engulf_clab_lab_registry_api import (
    LAB_REGISTRY_CONTEXT,
    LabRecord,
    LabRegistryError,
)

from engulf_clab_lab_registry.observe import observe_deployed_lab
from engulf_clab_lab_registry.plugin import LabRegistryPlugin
from engulf_clab_lab_registry.storage import StateLabRegistry


class MemoryState:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def exists(self, filename: str) -> bool:
        return filename in self.values

    def read_text(self, filename: str, **_kwargs: object) -> str:
        return self.values[filename]

    def write_text(self, filename: str, data: str, **_kwargs: object) -> None:
        self.values[filename] = data

    @contextmanager
    def transaction(self, **_kwargs: object) -> Iterator[MemoryState]:
        yield self


def state(value: MemoryState) -> StateStore:
    return cast(StateStore, value)


class StorageTest(unittest.TestCase):
    def test_round_trip_preserves_deployment_history_and_topology(self) -> None:
        memory = MemoryState()
        registry = StateLabRegistry(state(memory))
        root = Path("/labs/demo")
        registry.upsert(
            (
                LabRecord(
                    "demo",
                    root,
                    root / "lab.clab.yml",
                    frozenset({"sha256:old"}),
                    True,
                ),
            )
        )

        registry.upsert(
            (LabRecord("demo", root, None, frozenset({"sha256:new"}), False),)
        )

        record = registry.records()[0]
        self.assertEqual(record.topology, root / "lab.clab.yml")
        self.assertEqual(record.image_ids, frozenset({"sha256:new"}))
        self.assertTrue(record.ever_deployed)

    def test_malformed_state_is_rejected(self) -> None:
        memory = MemoryState()
        memory.values["labs.json"] = '{"version":1,"labs":"bad"}'

        with self.assertRaisesRegex(LabRegistryError, "invalid lab registry"):
            StateLabRegistry(state(memory)).records()


class ObservationTest(unittest.TestCase):
    def test_observes_exact_images_for_matching_deployed_lab(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            topology = root / "lab.clab.yml"
            topology.write_text(
                "name: demo\ntopology:\n  nodes: {}\n",
                encoding="utf-8",
            )
            inspected = json.dumps(
                [
                    {
                        "Image": "sha256:image",
                        "Config": {
                            "Labels": {
                                "containerlab": "demo",
                                "clab-topo-file": str(topology),
                            }
                        },
                    }
                ]
            )

            with patch(
                "engulf_clab_lab_registry.observe._run",
                side_effect=("container-id\n", inspected),
            ):
                record = observe_deployed_lab(topology, {})

        self.assertEqual(record.image_ids, frozenset({"sha256:image"}))
        self.assertTrue(record.ever_deployed)


class PluginTest(unittest.TestCase):
    def test_package_declares_schema_ordering(self) -> None:
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_lab_registry"
        ]
        self.assertEqual(
            group, {"engulf_clab.schema": "preprocess=after; postprocess=none"}
        )
        goal = project["entry-points"][
            "engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"
        ]
        application = project["entry-points"][
            "engulf.plugins.v1.application.engulf_clab"
        ]
        self.assertEqual(goal, application)
        self.assertEqual(tuple(goal), ("engulf_clab.lab_registry",))

    def test_before_goal_publishes_registry_handle(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        invocation = Invocation(("inspect",), Path("/labs"), {})

        result = LabRegistryPlugin().before_goal(invocation, api)

        self.assertIsNone(result)
        context, registry = api.set_context.call_args.args
        self.assertEqual(context, LAB_REGISTRY_CONTEXT)
        self.assertIsInstance(registry, StateLabRegistry)
        registry_reads = [
            call
            for call in api.get_context.call_args_list
            if call.args == (LAB_REGISTRY_CONTEXT,)
        ]
        self.assertEqual(len(registry_reads), 2)

    def test_successful_redeploy_updates_registry(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        topology = Path("/labs/demo/lab.clab.yml")
        record = LabRecord(
            "demo", topology.parent, topology, frozenset({"sha256:image"}), True
        )
        invocation = Invocation(("redeploy", "-t", str(topology)), Path("/labs"), {})

        with (
            patch(
                "engulf_clab_lab_registry.plugin.topology_path_from_args",
                return_value=topology,
            ),
            patch(
                "engulf_clab_lab_registry.plugin.observe_deployed_lab",
                return_value=record,
            ),
            patch("engulf_clab_lab_registry.plugin.StateLabRegistry") as registry,
        ):
            result = GoalResult.completed()
            returned = LabRegistryPlugin().after_goal(invocation, result, api)

        self.assertIs(returned, result)
        registry.return_value.upsert.assert_called_once_with((record,))

    def test_failed_deploy_does_not_update_registry(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        invocation = Invocation(("deploy",), Path("/labs"), {})

        with patch("engulf_clab_lab_registry.plugin.observe_deployed_lab") as observe:
            result = GoalResult.failed(1)
            returned = LabRegistryPlugin().after_goal(invocation, result, api)

        self.assertIs(returned, result)
        observe.assert_not_called()

    def test_tracking_failure_does_not_change_successful_deploy(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        invocation = Invocation(("deploy",), Path("/labs"), {})

        with patch(
            "engulf_clab_lab_registry.plugin.topology_path_from_args",
            side_effect=RuntimeError("broken observation"),
        ):
            result = GoalResult.completed()
            returned = LabRegistryPlugin().after_goal(invocation, result, api)

        self.assertIs(returned, result)
        api.logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
