from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engulf_api import ApplicationMetadata, BeforeGoalAPI, GoalResultStatus, Invocation

from engulf_clab_consumption.plugin import PLUGIN_SCHEMA, ConsumptionPlugin


class PluginTest(unittest.TestCase):
    def test_package_declares_schema_ordering(self) -> None:
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_consumption"
        ]
        self.assertEqual(group, {"engulf_clab.schema": "preprocess=after; postprocess=none"})
        self.assertNotIn("plugin_dependencies", ConsumptionPlugin.__dict__)

    def test_schema_declares_command_and_flags(self) -> None:
        application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="ECLAB",
            vendor="Engulf",
            product="ECLAB",
            version="1",
            short_product_name="eclab",
        )
        names = {option.name for option in PLUGIN_SCHEMA.options(application)}
        self.assertTrue({"consumption", "-t", "--all", "-p"}.issubset(names))

    def test_consumption_preempts_containerlab(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "eclab"
        invocation = Invocation(("consumption", "--all"), Path("/labs"), {})

        with patch("engulf_clab_consumption.plugin.run_consumption", return_value=7) as command:
            result = ConsumptionPlugin().before_goal(invocation, api)

        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(result.exit_code, 7)
        command.assert_called_once_with(
            ("--all",),
            cwd=Path("/labs"),
            environment={},
            program="eclab consumption",
            logger=api.logger,
        )

    def test_other_commands_continue(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        invocation = Invocation(("inspect",), Path.cwd(), {})
        with patch("engulf_clab_consumption.plugin.run_consumption") as command:
            self.assertIsNone(ConsumptionPlugin().before_goal(invocation, api))
        command.assert_not_called()

    def test_help_mentions_storage_split(self) -> None:
        help_text = ConsumptionPlugin().help(MagicMock())
        self.assertIn("unique/shared image storage", help_text)


if __name__ == "__main__":
    unittest.main()
