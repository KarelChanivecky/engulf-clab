"""Runtime contract for preparation unwind, which every stateful plugin relies on.

Plugins that acquire host resources in `prepare_call()` split their cleanup across
two paths, and which path runs is decided entirely by the goal. These tests pin
that decision so a runtime upgrade cannot move it silently.
"""

from __future__ import annotations

import contextlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from engulf_clab import ContainerlabApp

_PLUGIN = '''
from pathlib import Path

from engulf_executable_wrapper_api import ExecutableWrapperPlugin

LOG = Path({log!r})
NAME = {name!r}


def _record(phase):
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(NAME + ":" + phase + "\\n")


class Participant(ExecutableWrapperPlugin):
    plugin_id = {plugin_id!r}
    priority = {priority}

    def prepare_call(self, event, api):
        _record("prepare_call")
        {failure}

    def prepare_failed(self, event, api):
        _record("prepare_failed")

    def after_call(self, event, api):
        _record("after_call")


plugin = Participant()
'''


class PreparationUnwindContractTest(unittest.TestCase):
    """Three plugins prepare in priority order; the last one fails."""

    def _run(self, failure: str) -> list[str]:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "events.log"
            plugin_dir = root / "plugins"
            plugin_dir.mkdir()
            for name, priority, fails in (
                ("first", 100, ""),
                ("second", 50, ""),
                ("third", 10, failure),
            ):
                (plugin_dir / f"{name}.py").write_text(
                    _PLUGIN.format(
                        log=str(log),
                        name=name,
                        plugin_id=f"test.{name}",
                        priority=priority,
                        failure=fails or "pass",
                    ),
                    encoding="utf-8",
                )

            wrapper = ContainerlabApp(
                "/bin/true",
                plugin_dir=plugin_dir,
                discover_installed=False,
                state_home_resolver=lambda _context: root / "state-home",
            )
            with contextlib.suppress(BaseException):
                # Every failure propagates; the recorded event list is the outcome.
                wrapper.run(("deploy",))
            if not log.exists():
                return []
            return log.read_text(encoding="utf-8").split()

    # Preparation completes for first and second; third raises. Whatever ended the
    # phase, second and first unwind in reverse order and third never does.
    _UNWOUND: ClassVar[list[str]] = [
        "first:prepare_call",
        "second:prepare_call",
        "third:prepare_call",
        "second:prepare_failed",
        "first:prepare_failed",
    ]

    def test_an_exception_unwinds_the_plugins_that_prepared(self) -> None:
        self.assertEqual(self._run('raise RuntimeError("boom")'), self._UNWOUND)

    def test_an_interrupt_unwinds_the_same_plugins_in_the_same_order(self) -> None:
        """A Ctrl-C mid-preparation unwinds exactly as an ordinary failure does.

        The goal dispatches prepare_call one plugin at a time and tracks progress
        itself, so what unwinds no longer depends on the failure being an
        Exception. Interrupts still propagate unchanged.
        """
        self.assertEqual(self._run("raise KeyboardInterrupt()"), self._UNWOUND)

    def test_a_system_exit_also_unwinds(self) -> None:
        self.assertEqual(self._run("raise SystemExit(3)"), self._UNWOUND)

    def test_the_failing_plugin_never_receives_its_own_unwind(self) -> None:
        """Every recipient of prepare_failed prepared fully, without inspecting
        the event. The plugin that raised owns its partial work, which is why its
        prepare_call must clean up in a handler that catches BaseException
        rather than Exception.
        """
        for failure in (
            'raise RuntimeError("boom")',
            "raise KeyboardInterrupt()",
            "raise SystemExit(3)",
        ):
            with self.subTest(failure=failure):
                self.assertNotIn("third:prepare_failed", self._run(failure))

    def test_a_failed_preparation_dispatches_no_after_call(self) -> None:
        for failure in ('raise RuntimeError("boom")', "raise KeyboardInterrupt()"):
            with self.subTest(failure=failure):
                self.assertNotIn("after_call", " ".join(self._run(failure)))
