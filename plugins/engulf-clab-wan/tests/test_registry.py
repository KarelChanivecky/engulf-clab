from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager

from engulf_clab_wan.errors import WanError
from engulf_clab_wan.registry import (
    begin_rollback,
    bridge_metadata_for_workspace,
    claim_bridge,
    complete_provisioning,
    complete_release,
    complete_rollback,
    record_provision_step,
    release_bridge,
    workspace_bridge_names,
)


class MemoryState:
    def __init__(self) -> None:
        self.content: dict[str, str] = {}

    def exists(self, filename: str) -> bool:
        return filename in self.content

    def read_text(self, filename: str) -> str:
        return self.content[filename]

    def write_text(self, filename: str, data: str) -> None:
        self.content[filename] = data

    @contextmanager
    def transaction(self, *, timeout: float | None = None) -> Iterator[MemoryState]:
        del timeout
        yield self


def configuration(*, uplink: str = "eth0") -> dict[str, object]:
    return {
        "name": "wan",
        "subnet": "198.19.0.0/24",
        "gateway": "198.19.0.1",
        "pool_start": "198.19.0.100",
        "pool_end": "198.19.0.200",
        "dns": "1.1.1.1",
        "lease_time": 43200,
        "uplink": uplink,
    }


class RegistryTest(unittest.TestCase):
    def test_final_workspace_claimant_receives_cleanup_metadata(self) -> None:
        state = MemoryState()
        first = "/labs/first"
        second = "/labs/second"
        config = configuration()

        needs_provisioning, _entry = claim_bridge(
            state,
            workspace=first,
            configuration=config,
        )
        self.assertTrue(needs_provisioning)
        metadata = {**config, "created": True, "gateway_added": True}
        complete_provisioning(state, "wan", metadata)

        needs_provisioning, _entry = claim_bridge(
            state,
            workspace=second,
            configuration=config,
        )
        self.assertFalse(needs_provisioning)
        self.assertIsNone(release_bridge(state, workspace=first, name="wan"))
        self.assertEqual(release_bridge(state, workspace=second, name="wan"), metadata)
        self.assertTrue(complete_release(state, "wan"))

    def test_conflicting_claim_is_rejected(self) -> None:
        state = MemoryState()
        config = configuration()
        claim_bridge(state, workspace="/labs/first", configuration=config)
        complete_provisioning(
            state, "wan", {**config, "created": True, "gateway_added": True}
        )

        with self.assertRaisesRegex(WanError, "conflicting"):
            claim_bridge(
                state,
                workspace="/labs/second",
                configuration=configuration(uplink="eth1"),
            )

    def test_workspace_metadata_is_only_a_bridge_claim_list(self) -> None:
        state = MemoryState()
        bridge_metadata_for_workspace(state, ["wan2", "wan", "wan"])
        self.assertEqual(workspace_bridge_names(state), ["wan", "wan2"])

    def test_provisioning_journal_recovers_only_owned_steps(self) -> None:
        state = MemoryState()
        config = configuration()
        claim_bridge(state, workspace="/labs/first", configuration=config)
        record_provision_step(state, "wan", "bridge-created")
        record_provision_step(state, "wan", "gateway-added")

        metadata = begin_rollback(state, "wan")

        self.assertEqual(
            metadata,
            {**config, "created": True, "gateway_added": True},
        )
        self.assertTrue(complete_rollback(state, "wan"))


if __name__ == "__main__":
    unittest.main()
