from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from engulf_api import InvocationAPI

from engulf_clab_lab_registry_api import (
    LAB_REGISTRY_CONTEXT,
    LabRecord,
    LabRegistryError,
    lab_registry,
)


class Registry:
    def records(self) -> tuple[LabRecord, ...]:
        return ()

    def upsert(self, records: tuple[LabRecord, ...]) -> None:
        del records


class ContractTest(unittest.TestCase):
    def test_record_requires_absolute_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute Path"):
            LabRecord("demo", Path("relative"), None, frozenset(), False)

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


if __name__ == "__main__":
    unittest.main()
