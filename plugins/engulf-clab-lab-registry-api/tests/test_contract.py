from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

from engulf_api import InvocationAPI

from engulf_clab_lab_registry_api import (
    LAB_REGISTRY_COMMIT_CONTEXT,
    LAB_REGISTRY_CONTEXT,
    LabRecord,
    LabRegistry,
    LabRegistryError,
    RegistryCommit,
    Workspace,
    lab_registry,
)


class Registry:
    persistent = True
    revision = 0

    def records(self) -> tuple[LabRecord, ...]:
        return ()

    def upsert(self, records: tuple[LabRecord, ...]) -> None:
        del records


class ContractTest(unittest.TestCase):
    def test_record_requires_absolute_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute Path"):
            Workspace(Path("relative"))

    def test_workspace_canonicalizes_the_path_and_record_key_uses_it(self) -> None:
        workspace = Workspace(Path("/labs/child/.."))
        record = LabRecord("demo", workspace, None, frozenset(), False)

        self.assertEqual(workspace.path, Path("/labs"))
        self.assertIs(record.workspace, workspace)
        self.assertEqual(record.directory, Path("/labs"))
        self.assertEqual(record.key, ("demo", Path("/labs")))

    def test_record_converts_legacy_path_input_at_the_boundary(self) -> None:
        record = LabRecord(
            "demo", Path("/labs/child/.."), None, frozenset(), False
        )

        self.assertIsInstance(record.workspace, Workspace)
        self.assertEqual(record.workspace.path, Path("/labs"))

    def test_context_returns_structural_registry(self) -> None:
        api = MagicMock(spec=InvocationAPI)
        registry = Registry()
        api.get_context.return_value = registry

        self.assertIs(lab_registry(api), registry)
        api.get_context.assert_called_once_with(LAB_REGISTRY_CONTEXT)

    def test_missing_context_is_actionable(self) -> None:
        api = MagicMock(spec=InvocationAPI)
        api.get_context.return_value = None

        with self.assertRaisesRegex(LabRegistryError, "install and activate"):
            lab_registry(api)

    def test_registry_without_fence_members_is_not_a_registry(self) -> None:
        """A stale provider lacking the durability members must not match."""

        class Stale:
            def records(self) -> tuple[LabRecord, ...]:
                return ()

            def upsert(self, records: tuple[LabRecord, ...]) -> None:
                del records

        api = MagicMock(spec=InvocationAPI)
        api.get_context.return_value = Stale()

        with self.assertRaisesRegex(LabRegistryError, "install and activate"):
            lab_registry(api)

    def test_protocol_exposes_fence_and_persistence(self) -> None:
        self.assertTrue(isinstance(Registry(), LabRegistry))

    def test_commit_context_is_namespaced_and_outcome_is_immutable(self) -> None:
        self.assertEqual(
            LAB_REGISTRY_COMMIT_CONTEXT, "engulf_clab.lab_registry.commit"
        )
        record = LabRecord("demo", Path("/labs/demo"), None, frozenset(), False)
        outcome = RegistryCommit(True, 4, (record,))
        self.assertTrue(outcome.committed)
        self.assertEqual(outcome.revision, 4)
        self.assertEqual(outcome.records, (record,))
        self.assertIsNone(outcome.error)
        with self.assertRaises(FrozenInstanceError):
            outcome.committed = False  # type: ignore[misc]

    def test_uncommitted_outcome_defaults_to_no_records(self) -> None:
        outcome = RegistryCommit(committed=False, revision=2, error="unavailable")
        self.assertEqual(outcome.records, ())
        self.assertEqual(outcome.error, "unavailable")


if __name__ == "__main__":
    unittest.main()
