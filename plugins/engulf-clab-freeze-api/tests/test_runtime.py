from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engulf_clab_freeze_api import (
    FreezeError,
    discover_runtime_providers,
    runtime_provider,
)


class Provider:
    edition = "example"

    def capture(self, environment, user_state):
        return {}

    def prepare_archive(self, root, mode, tools, environment, user_state, warnings):
        return None

    def check_recipient(self, tools, environment, user_state):
        return []

    def prepare_recipient(self, root, mode, tools, environment, user_state, notes):
        return None

    def launcher(self, topology, mode, tools):
        return ""


def test_runtime_provider_is_selected_by_edition():
    entry = SimpleNamespace(name="example", load=lambda: Provider)
    with patch("engulf_clab_freeze_api.runtime.importlib.metadata.entry_points", return_value=[entry]):
        assert runtime_provider("example").edition == "example"
        with pytest.raises(FreezeError, match="no freeze runtime provider"):
            runtime_provider("missing")


def test_runtime_provider_rejects_entry_point_name_mismatch():
    entry = SimpleNamespace(name="wrong", load=lambda: Provider)
    with (
        patch("engulf_clab_freeze_api.runtime.importlib.metadata.entry_points", return_value=[entry]),
        pytest.raises(FreezeError, match="invalid contract or edition"),
    ):
        discover_runtime_providers()
