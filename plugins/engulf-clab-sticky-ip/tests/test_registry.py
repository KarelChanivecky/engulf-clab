from __future__ import annotations

import contextlib
import json
import unittest

from engulf_clab_sticky_ip.allocation import Family, StickyIPError
from engulf_clab_sticky_ip.registry import (
    Allocation,
    Registry,
    finish_attempt,
    load_registry,
    record_pending,
    release_lab,
    rollback_attempt,
)


class MemoryState:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def exists(self, path: str) -> bool:
        return path in self.files

    def read_text(self, path: str) -> str:
        return self.files[path]

    def write_text(self, path: str, value: str) -> None:
        self.files[path] = value

    @contextlib.contextmanager
    def transaction(self):  # type: ignore[no-untyped-def]
        yield self


def allocation(identifier: str, status: str, *, attempt: str | None = None) -> Allocation:
    return Allocation(
        identifier,
        "lab-key",
        "/tmp/lab",
        "lab",
        Family.IPV4,
        "lab-network",
        "10.60.0.0/24",
        1,
        {"a": "10.60.0.2"},
        status,
        1,
        True,
        attempt,
    )


class RegistryTest(unittest.TestCase):
    def test_pending_attempt_rolls_back_evicted_history(self) -> None:
        state = MemoryState()
        old = allocation("old", "inactive")
        expected = Registry(0, 1, {"ipv4": (0, -1), "ipv6": (0, -1)}, (old,))
        pending = allocation("new", "pending", attempt="attempt")

        attempt = record_pending(state, expected, pending, evicted=(old,))
        rollback_attempt(state, attempt)

        current = load_registry(state)
        self.assertEqual(current.allocations, (old,))

    def test_success_activates_new_claim_and_destroy_releases_it(self) -> None:
        state = MemoryState()
        expected = Registry.empty()
        pending = allocation("new", "pending", attempt="attempt")
        attempt = record_pending(state, expected, pending)

        finish_attempt(state, attempt, success=True)
        self.assertEqual(load_registry(state).allocations[0].status, "active")

        release_lab(state, "lab-key")
        self.assertEqual(load_registry(state).allocations[0].status, "inactive")

    def test_started_failure_stays_uncertain(self) -> None:
        state = MemoryState()
        pending = allocation("new", "pending", attempt="attempt")
        attempt = record_pending(state, Registry.empty(), pending)

        finish_attempt(state, attempt, success=False)

        self.assertEqual(load_registry(state).allocations[0].status, "uncertain")

    def test_invalid_persisted_allocation_fails_closed(self) -> None:
        state = MemoryState()
        document = Registry(
            0,
            1,
            {"ipv4": (0, -1), "ipv6": (0, -1)},
            (allocation("bad", "active"),),
        ).to_json()
        document["allocations"][0]["subnet"] = "203.0.113.0/24"
        state.files["sticky-ip.json"] = json.dumps(document)

        with self.assertRaisesRegex(StickyIPError, "public subnet"):
            load_registry(state)


if __name__ == "__main__":
    unittest.main()
