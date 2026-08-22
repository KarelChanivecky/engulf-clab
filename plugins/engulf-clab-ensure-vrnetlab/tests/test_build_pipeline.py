from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from engulf_clab import ContainerlabApp
from engulf_executable_wrapper_api import CallOutcome, OutcomeKind

from engulf_clab_ensure_vrnetlab import ENSURE_VRNETLAB_PLUGIN_ID


def write_plugin_directory(directory: Path) -> Path:
    plugin_dir = directory / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "ensure.py").write_text(
        "from engulf_clab_ensure_vrnetlab.plugin import plugin\n",
        encoding="utf-8",
    )
    (plugin_dir / "topology.py").write_text(
        "from engulf_clab_lab_parser import plugin\n",
        encoding="utf-8",
    )
    (plugin_dir / "vrnetlab.py").write_text(
        "from engulf_clab_vrnetlab_build.plugin import plugin\n",
        encoding="utf-8",
    )
    (plugin_dir / "schema.py").write_text(
        "from engulf_clab_schema import plugin\n",
        encoding="utf-8",
    )
    return plugin_dir


class BuildPipelineIntegrationTest(unittest.TestCase):
    def test_plugins_render_help_through_runtime_diagnostics_api(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = ContainerlabApp(
                "/bin/true",
                plugin_dir=write_plugin_directory(root),
                discover_installed=False,
                state_home_resolver=lambda _context: root / "state",
            )

            with (
                patch.object(
                    wrapper.goal,
                    "_execute",
                    return_value=(
                        CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
                        0.0,
                    ),
                ),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(wrapper.run(("--help",)), 0)

    def test_ensure_plugin_publishes_checkout_before_build_plugin(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            topology.write_text(
                """
name: pipeline
topology:
  nodes:
    router:
      image: vrnetlab/vendor_router:1
      env:
        ECLAB_VRNETLAB_TYPE: vendor/router
""",
                encoding="utf-8",
            )
            checkout = root / "vrnetlab"

            wrapper = ContainerlabApp(
                "/bin/true",
                plugin_dir=write_plugin_directory(root),
                discover_installed=False,
                state_home_resolver=lambda _context: root / "state",
            )

            with (
                patch(
                    "engulf_clab_ensure_vrnetlab.plugin.ensure_checkout",
                    return_value=checkout,
                ) as ensure,
                patch("engulf_clab_ensure_vrnetlab.plugin.require_vrnetlab_dependencies"),
                patch("engulf_clab_ensure_vrnetlab.plugin.update_vrnetlab"),
                patch("engulf_clab_vrnetlab_build.plugin.ensure_images") as build,
            ):
                result = wrapper.run(("deploy", "-t", str(topology)))

            self.assertEqual(result, 0)
            self.assertLess(
                [item.plugin_id for item in wrapper.plugins].index("engulf_clab.lab_parser"),
                [item.plugin_id for item in wrapper.plugins].index(ENSURE_VRNETLAB_PLUGIN_ID),
            )
            ensure.assert_called_once()
            self.assertEqual(build.call_args.kwargs["checkout_context"], str(checkout))


if __name__ == "__main__":
    unittest.main()
