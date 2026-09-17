from __future__ import annotations

import json
import tomllib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import ANY, MagicMock, patch

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    StateStore,
)
from engulf_clab_lab_registry_api import (
    LAB_REGISTRY_COMMIT_CONTEXT,
    LAB_REGISTRY_CONTEXT,
    LabRecord,
    LabRegistryError,
    RegistryCommit,
)

from engulf_clab_lab_registry.observe import observe_deployed_lab
from engulf_clab_lab_registry.plugin import LabRegistryPlugin
from engulf_clab_lab_registry.storage import SessionLabRegistry, StateLabRegistry


class MemoryState:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.fail = False
        self.write_fail = False

    def _check(self) -> None:
        if self.fail:
            raise AssertionError("state accessed outside its owning callback")

    def exists(self, filename: str) -> bool:
        self._check()
        return filename in self.values

    def read_text(self, filename: str, **_kwargs: object) -> str:
        self._check()
        return self.values[filename]

    def write_text(self, filename: str, data: str, **_kwargs: object) -> None:
        self._check()
        if self.write_fail:
            raise OSError("state is not writable")
        self.values[filename] = data

    @contextmanager
    def transaction(self, **_kwargs: object) -> Iterator[MemoryState]:
        self._check()
        yield self


def _record() -> LabRecord:
    root = Path("/labs/demo")
    return LabRecord(
        "demo", root, root / "lab.clab.yml", frozenset({"sha256:image"}), True
    )


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

    def test_before_goal_publishes_snapshot_without_a_state_handle(self) -> None:
        memory = MemoryState()
        StateLabRegistry(state(memory)).upsert((_record(),))
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.state.return_value = state(memory)
        invocation = Invocation(("inspect",), Path("/labs"), {})

        result = LabRegistryPlugin().before_goal(invocation, api)

        self.assertIsNone(result)
        context, registry = api.set_context.call_args.args
        self.assertEqual(context, LAB_REGISTRY_CONTEXT)
        self.assertIsInstance(registry, SessionLabRegistry)
        self.assertEqual(registry.records(), (_record(),))
        registry_reads = [
            call
            for call in api.get_context.call_args_list
            if call.args == (LAB_REGISTRY_CONTEXT,)
        ]
        self.assertEqual(len(registry_reads), 2)

    def test_published_registry_survives_the_publisher_deactivation(self) -> None:
        """A reader in a later callback must not touch the publisher's store."""
        memory = MemoryState()
        StateLabRegistry(state(memory)).upsert((_record(),))
        store = state(memory)
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.state.return_value = store
        invocation = Invocation(("consumption", "--all"), Path("/labs"), {})

        LabRegistryPlugin().before_goal(invocation, api)
        registry = api.set_context.call_args.args[1]
        # Simulate deactivation: any further store access would raise.
        memory.fail = True

        self.assertEqual(registry.records(), (_record(),))
        registry.upsert(
            (LabRecord("other", Path("/labs/other"), None, frozenset(), False),)
        )
        self.assertEqual(len(registry.records()), 2)

    def test_unreadable_registry_serves_empty_and_refuses_to_persist(self) -> None:
        memory = MemoryState()
        memory.values["labs.json"] = '{"version":1,"labs":"bad"}'
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.state.return_value = state(memory)
        invocation = Invocation(("consumption",), Path("/labs"), {})

        result = LabRegistryPlugin().before_goal(invocation, api)

        self.assertIsNone(result)
        registry = api.set_context.call_args.args[1]
        self.assertEqual(registry.records(), ())
        self.assertFalse(registry.persistent)
        api.logger.warning.assert_any_call("could not read lab registry: %s", ANY)

    def test_reader_updates_are_persisted_after_the_goal(self) -> None:
        memory = MemoryState()
        session = SessionLabRegistry()
        session.upsert((_record(),))
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = session
        api.state.return_value = state(memory)
        invocation = Invocation(("consumption", "--all"), Path("/labs"), {})

        result = GoalResult.completed()
        returned = LabRegistryPlugin().after_goal(invocation, result, api)

        self.assertIs(returned, result)
        self.assertEqual(StateLabRegistry(state(memory)).records(), (_record(),))

    def test_unpersistable_registry_is_not_written_back(self) -> None:
        memory = MemoryState()
        memory.values["labs.json"] = '{"version":1,"labs":"bad"}'
        session = SessionLabRegistry(persistent=False)
        session.upsert((_record(),))
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = session
        api.state.return_value = state(memory)
        invocation = Invocation(("consumption",), Path("/labs"), {})

        LabRegistryPlugin().after_goal(invocation, GoalResult.completed(), api)

        self.assertEqual(memory.values["labs.json"], '{"version":1,"labs":"bad"}')

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
            session = SessionLabRegistry()
            api.get_context.return_value = session
            result = GoalResult.completed()
            returned = LabRegistryPlugin().after_goal(invocation, result, api)

        self.assertIs(returned, result)
        registry.return_value.commit.assert_called_once_with(session)

    def test_failed_deploy_does_not_update_registry(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = SessionLabRegistry()
        invocation = Invocation(("deploy",), Path("/labs"), {})

        with patch("engulf_clab_lab_registry.plugin.observe_deployed_lab") as observe:
            result = GoalResult.failed(1)
            returned = LabRegistryPlugin().after_goal(invocation, result, api)

        self.assertIs(returned, result)
        observe.assert_not_called()

    def test_tracking_failure_does_not_change_successful_deploy(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = SessionLabRegistry()
        # A working store, so the only failure under test is the observation.
        api.state.return_value = state(MemoryState())
        invocation = Invocation(("deploy",), Path("/labs"), {})

        with patch(
            "engulf_clab_lab_registry.plugin.topology_path_from_args",
            side_effect=RuntimeError("broken observation"),
        ):
            result = GoalResult.completed()
            returned = LabRegistryPlugin().after_goal(invocation, result, api)

        self.assertIs(returned, result)
        api.logger.warning.assert_called_once()


def _published_commit(api: MagicMock) -> RegistryCommit:
    writes = [
        call
        for call in api.set_context.call_args_list
        if call.args[0] == LAB_REGISTRY_COMMIT_CONTEXT
    ]
    if len(writes) != 1:
        raise AssertionError(f"expected one commit publication, saw {len(writes)}")
    return cast(RegistryCommit, writes[0].args[1])


class CommitTest(unittest.TestCase):
    """Durability and ownership-fence behavior of the registry owner."""

    def test_revision_bumps_only_on_content_change(self) -> None:
        memory = MemoryState()
        registry = StateLabRegistry(state(memory))
        record = _record()
        self.assertEqual(registry.revision(), 0)

        registry.upsert((record,))
        self.assertEqual(registry.revision(), 1)

        # An idempotent retry renders identical content: no bump.
        registry.upsert((record,))
        self.assertEqual(registry.revision(), 1)

        registry.upsert(
            (
                LabRecord(
                    record.name,
                    record.directory,
                    record.topology,
                    frozenset({"sha256:changed"}),
                    record.ever_deployed,
                ),
            )
        )
        self.assertEqual(registry.revision(), 2)

    def test_payload_without_revision_stays_readable(self) -> None:
        memory = MemoryState()
        memory.values["labs.json"] = json.dumps(
            {
                "version": 1,
                "labs": [
                    {
                        "name": "demo",
                        "directory": "/labs/demo",
                        "topology": None,
                        "image_ids": [],
                        "ever_deployed": False,
                    }
                ],
            }
        )

        registry = StateLabRegistry(state(memory))

        self.assertEqual(registry.revision(), 0)
        self.assertEqual(registry.records()[0].name, "demo")

    def test_commit_of_a_nonpersistent_session_writes_nothing(self) -> None:
        memory = MemoryState()
        memory.values["labs.json"] = '{"version":1,"labs":"bad"}'
        session = SessionLabRegistry(persistent=False)
        session.upsert((_record(),))

        outcome = StateLabRegistry(state(memory)).commit(session)

        self.assertFalse(outcome.committed)
        self.assertIsNotNone(outcome.error)
        # The unparsable file survives for inspection.
        self.assertEqual(memory.values["labs.json"], '{"version":1,"labs":"bad"}')

    def test_commit_read_only_when_nothing_is_pending(self) -> None:
        memory = MemoryState()
        StateLabRegistry(state(memory)).upsert((_record(),))
        session = SessionLabRegistry(
            StateLabRegistry(state(memory)).records(),
            revision=StateLabRegistry(state(memory)).revision(),
        )

        outcome = StateLabRegistry(state(memory)).commit(session)

        self.assertTrue(outcome.committed)
        self.assertEqual(outcome.revision, 1)
        self.assertEqual(outcome.records, (_record(),))

    def test_commit_surfaces_a_write_failure(self) -> None:
        memory = MemoryState()
        session = SessionLabRegistry()
        session.upsert((_record(),))
        memory.write_fail = True

        with self.assertRaises(OSError):
            StateLabRegistry(state(memory)).commit(session)

    def test_stale_same_identity_update_keeps_the_newer_entry(self) -> None:
        """A's stale pending update must not replace B's newer entry."""
        memory = MemoryState()
        store = StateLabRegistry(state(memory))
        base = _record()
        store.upsert((base,))
        # A loads revision 1, planning to refresh its image ownership.
        session = SessionLabRegistry(store.records(), revision=store.revision())
        # B registers a newer same-identity entry first.
        newer = LabRecord(
            base.name,
            base.directory,
            None,
            frozenset({"sha256:bee"}),
            False,
        )
        store.upsert((newer,))

        session.upsert(
            (
                LabRecord(
                    base.name,
                    base.directory,
                    None,
                    frozenset({"sha256:aye"}),
                    True,
                ),
            )
        )
        outcome = store.commit(session)

        self.assertTrue(outcome.committed)
        record = {item.name: item for item in outcome.records}[base.name]
        # Image ownership is B's; the monotone deployment history is or-merged.
        self.assertEqual(record.image_ids, frozenset({"sha256:bee"}))
        self.assertTrue(record.ever_deployed)
        self.assertEqual(record.topology, base.topology)

    def test_commit_keeps_entries_from_both_writers(self) -> None:
        memory = MemoryState()
        store = StateLabRegistry(state(memory))
        base = _record()
        store.upsert((base,))
        session = SessionLabRegistry(store.records(), revision=store.revision())
        other = LabRecord("other", Path("/labs/other"), None, frozenset({"sha256:o"}), False)
        store.upsert((other,))

        session.upsert(
            (LabRecord(base.name, base.directory, None, frozenset({"sha256:a"}), True),)
        )
        outcome = store.commit(session)

        names = {item.name for item in outcome.records}
        self.assertEqual(names, {"demo", "other"})

    def test_committed_snapshot_is_visible_to_a_new_invocation(self) -> None:
        """A crash after commit but before deletion still preserves state."""
        memory = MemoryState()
        session = SessionLabRegistry()
        session.upsert(
            (LabRecord("demo", Path("/labs/demo"), None, frozenset({"sha256:a"}), True),)
        )

        outcome = StateLabRegistry(state(memory)).commit(session)

        self.assertTrue(outcome.committed)
        fresh = StateLabRegistry(state(memory))
        self.assertEqual(fresh.records()[0].image_ids, frozenset({"sha256:a"}))
        self.assertEqual(fresh.revision(), outcome.revision)

    def test_after_goal_publishes_commit_outcome_on_success(self) -> None:
        memory = MemoryState()
        record = _record()
        session = SessionLabRegistry()
        session.upsert((record,))
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = session
        api.state.return_value = state(memory)
        invocation = Invocation(("consumption", "--all"), Path("/labs"), {})

        LabRegistryPlugin().after_goal(invocation, GoalResult.completed(), api)

        outcome = _published_commit(api)
        self.assertTrue(outcome.committed)
        self.assertEqual(outcome.revision, 1)
        self.assertIn(record, outcome.records)
        # The publication is acknowledged so non-reclaim runs stay quiet.
        reads = [
            call
            for call in api.get_context.call_args_list
            if call.args == (LAB_REGISTRY_COMMIT_CONTEXT,)
        ]
        self.assertTrue(reads)

    def test_after_goal_publishes_failure_when_the_write_fails(self) -> None:
        memory = MemoryState()
        session = SessionLabRegistry(revision=3)
        session.upsert((_record(),))
        memory.write_fail = True
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = session
        api.state.return_value = state(memory)
        invocation = Invocation(("consumption",), Path("/labs"), {})

        LabRegistryPlugin().after_goal(invocation, GoalResult.completed(), api)

        outcome = _published_commit(api)
        self.assertFalse(outcome.committed)
        self.assertEqual(outcome.revision, 3)
        api.logger.warning.assert_called_once()

    def test_after_goal_publishes_failure_for_an_unpersistable_session(self) -> None:
        memory = MemoryState()
        memory.values["labs.json"] = '{"version":1,"labs":"bad"}'
        session = SessionLabRegistry(persistent=False)
        session.upsert((_record(),))
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = session
        api.state.return_value = state(memory)
        invocation = Invocation(("consumption",), Path("/labs"), {})

        LabRegistryPlugin().after_goal(invocation, GoalResult.completed(), api)

        outcome = _published_commit(api)
        self.assertFalse(outcome.committed)
        self.assertEqual(memory.values["labs.json"], '{"version":1,"labs":"bad"}')


if __name__ == "__main__":
    unittest.main()
