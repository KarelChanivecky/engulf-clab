from __future__ import annotations

import argparse
import unittest
from pathlib import Path

from engulf_clab_freeze_api import DefrostContext, FreezeContext


class ContextTest(unittest.TestCase):
    def test_contexts_are_immutable_and_path_oriented(self) -> None:
        frozen = FreezeContext(
            Path("/lab/lab.clab.yml"), Path("/tmp/lab/lab.clab.yml"),
            Path("/lab"), Path("/tmp/lab"), Path("/state/work"), Path("/state/user"),
            argparse.Namespace(), {},
        )
        self.assertEqual(frozen.user_state, Path("/state/user"))
        restored = DefrostContext(
            Path("/tmp/lab/lab.clab.yml"), Path("/tmp/lab"), Path("/labs/lab"),
            {}, argparse.Namespace(), {}, Path("/state/user"),
        )
        self.assertEqual(restored.user_state, Path("/state/user"))
