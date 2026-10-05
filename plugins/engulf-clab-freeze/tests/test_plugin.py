from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import tomllib
from engulf_api import (
    ApplicationMetadata,
    BeforeGoalAPI,
    GoalResultStatus,
    Invocation,
    StateScope,
    WorkspaceState,
)
from engulf_clab_freeze.plugin import (
    PLUGIN_SCHEMA,
    FreezePlugin,
    _offer_license_pool_setup,
)
from engulf_clab_license_pool_lib import (
    LICENSE_POOL_AVAILABILITY_CONTEXT,
    LicensePoolAvailability,
)
from engulf_clab_schema_api import (
    SCHEMA_SOURCE_CONTEXT,
    SCHEMA_VRNETLAB_SOURCE_CONTEXT,
    register_schema_completions,
)
from engulf_clab_vrnetlab_build_api import VRNETLAB_SOURCE_PROVENANCE_CONTEXT
from engulf_docker_image_api import DOCKER_IMAGE_PROVENANCE_CONTEXT
from engulf_executable_wrapper_api import (
    CompletionContext,
    CompletionRegistry,
    Shell,
    invoke_provider,
    normalize_candidate,
)


class FreezePluginTest(unittest.TestCase):
    def test_runtime_bundle_flag_is_offered_by_schema_completion(self) -> None:
        application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="ECLAB",
            vendor="ECLAB",
            product="Engulf Containerlab",
            short_product_name="eclab",
            version="1.0",
        )
        registry = CompletionRegistry()
        register_schema_completions(registry, PLUGIN_SCHEMA, application)
        context = CompletionContext(
            Shell.BASH,
            "eclab",
            "containerlab",
            ("freeze", "--eclab-with-runt"),
            1,
        )

        candidates = tuple(
            normalize_candidate(item).value
            for item in invoke_provider(registry.providers[0], context)
        )

        self.assertIn("--eclab-with-runtime", candidates)

    def test_dependency_is_declared_in_package_metadata(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_freeze"
        ]

        self.assertEqual(
            group,
            {
                "engulf_clab.schema": "preprocess=after; postprocess=none",
                "engulf_clab.license_pool": "preprocess=before; postprocess=none",
                "engulf_clab.image_build": "preprocess=before; postprocess=none",
                "engulf_clab.vrnetlab_build": "preprocess=before; postprocess=none",
            },
        )
        self.assertNotIn("plugin_dependencies", FreezePlugin.__dict__)
        self.assertIn(DOCKER_IMAGE_PROVENANCE_CONTEXT, FreezePlugin.context_reads)
        self.assertIn(VRNETLAB_SOURCE_PROVENANCE_CONTEXT, FreezePlugin.context_reads)
        self.assertIn(
            LICENSE_POOL_AVAILABILITY_CONTEXT, FreezePlugin.context_reads
        )
        self.assertIn(
            "engulf-clab-license-pool-lib>=0.2,<3",
            project["dependencies"],
        )
        self.assertIn("engulf-clab-license-pool>=0.2,<1", project["dependencies"])

    def test_freeze_runs_before_the_wrapped_goal_and_returns_its_exit_code(
        self,
    ) -> None:
        workspace = MagicMock(spec=WorkspaceState)
        workspace.root = Path("/labs/demo")
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.state.return_value = workspace
        api.leases.return_value.__enter__.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(
            ("freeze", "--eclab-output", "share.tar.gz"), Path("/labs/demo"), {}
        )

        with patch(
            "engulf_clab_freeze.plugin.run_freeze_command", return_value=13
        ) as command:
            result = FreezePlugin().before_goal(invocation, api)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(result.exit_code, 13)
        self.assertEqual(
            api.state.call_args_list,
            [call(StateScope.WORKSPACE), call(StateScope.USER)],
        )
        # Lease name is fixed regardless of edition, so two differently-branded
        # editions freezing the same workspace concurrently block each other.
        api.leases.assert_called_once_with(("eclab-freeze:/labs/demo",))
        command.assert_called_once_with(
            ["--eclab-output", "share.tar.gz"],
            workspace,
            user_state=workspace,
            program="fclab freeze",
            application_name="fclab",
            logger=api.logger,
            environment=invocation.environment,
            requirements=(),
        )
        api.get_context.assert_has_calls(
            [
                call(SCHEMA_SOURCE_CONTEXT),
                call(SCHEMA_VRNETLAB_SOURCE_CONTEXT),
            ]
        )

    def test_offline_freeze_receives_user_state_for_managed_tools(self) -> None:
        workspace = MagicMock(spec=WorkspaceState)
        workspace.root = Path("/labs/demo")
        user_state = MagicMock(spec=WorkspaceState)
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.state.side_effect = lambda scope: {
            StateScope.WORKSPACE: workspace,
            StateScope.USER: user_state,
        }[scope]
        api.leases.return_value.__enter__.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(("freeze", "--eclab-offline"), Path("/labs/demo"), {})

        with patch(
            "engulf_clab_freeze.plugin.run_freeze_command", return_value=0
        ) as command:
            FreezePlugin().before_goal(invocation, api)

        command.assert_called_once_with(
            ["--eclab-offline"],
            workspace,
            user_state=user_state,
            program="fclab freeze",
            application_name="fclab",
            logger=api.logger,
            environment=invocation.environment,
            requirements=(),
        )
        self.assertEqual(
            api.state.call_args_list,
            [call(StateScope.WORKSPACE), call(StateScope.USER)],
        )
        api.leases.assert_called_once_with(
            (
                "eclab-freeze:/labs/demo",
                "repository-cache:containerlab",
                "repository-cache:vrnetlab",
            )
        )

    def test_defrost_runs_before_the_wrapped_goal_under_a_destination_lease(
        self,
    ) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.leases.return_value.__enter__.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(
            ("defrost", "share.tar.gz", "--eclab-output", "demo"), Path("/labs"), {}
        )

        with patch(
            "engulf_clab_freeze.plugin.run_defrost_command", return_value=7
        ) as command:
            result = FreezePlugin().before_goal(invocation, api)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(result.exit_code, 7)
        # Defrost uses its own state only for recipient setup. Pool availability
        # comes from the owning plugin's invocation context.
        api.state.assert_called_once_with(StateScope.USER)
        api.leases.assert_called_once_with(("eclab-defrost:/labs/demo",))
        command.assert_called_once_with(
            ["share.tar.gz", "--eclab-output", "demo"],
            program="fclab defrost",
            application_name="fclab",
            logger=api.logger,
            environment=invocation.environment,
            cwd=invocation.cwd,
            user_state=api.state.return_value.directory,
            license_pools_registered=None,
            setup_license_pool=None,
        )
        api.get_context.assert_has_calls(
            [
                call(SCHEMA_SOURCE_CONTEXT),
                call(SCHEMA_VRNETLAB_SOURCE_CONTEXT),
                call(LICENSE_POOL_AVAILABILITY_CONTEXT, None),
            ]
        )

    def test_defrost_uses_license_pool_availability_from_context(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        api.get_context.side_effect = lambda key, default=None: (
            LicensePoolAvailability(True)
            if key == LICENSE_POOL_AVAILABILITY_CONTEXT
            else default
        )
        api.leases.return_value.__enter__.return_value = None
        invocation = Invocation(("defrost", "share.tar.gz"), Path("/labs"), {})

        with patch(
            "engulf_clab_freeze.plugin.run_defrost_command", return_value=0
        ) as command:
            FreezePlugin().before_goal(invocation, api)

        command.assert_called_once()
        self.assertIs(command.call_args.kwargs["license_pools_registered"], True)
        self.assertIsNone(command.call_args.kwargs["setup_license_pool"])

    def test_pool_setup_creates_path_then_initializes_pool_from_inside(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root / "license-data" / "fortigate"
            launcher = root / "runtime" / "bin" / "fclab"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            caller = root / "caller"
            caller.mkdir()
            stage = root / ".extract"
            stage.mkdir()
            invocation = Invocation(
                ("defrost",),
                stage,
                {
                    "ECLAB_FREEZE_CALLER_CWD": str(caller),
                    "HOME": str(root),
                },
            )
            logger = MagicMock()
            with (
                patch("engulf_clab_freeze.plugin.sys.stdin") as stdin,
                patch(
                    "builtins.input",
                    side_effect=["yes", "~/license-data/fortigate"],
                ),
                patch("engulf_clab_freeze.plugin.sys.argv", [str(launcher)]),
                patch(
                    "engulf_clab_freeze.plugin.subprocess.run",
                    return_value=MagicMock(returncode=0),
                ) as run,
            ):
                stdin.isatty.return_value = True
                self.assertTrue(_offer_license_pool_setup(invocation, "fclab", logger))

            run.assert_called_once()
            self.assertEqual(
                run.call_args.args[0],
                [str(launcher), "init-license-pool", str(pool.resolve())],
            )
            self.assertEqual(run.call_args.kwargs["cwd"], pool.resolve())
            self.assertTrue(pool.is_dir())

    def test_non_freeze_invocations_continue_to_the_wrapped_goal(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "fclab"
        invocation = Invocation(("deploy", "-t", "lab.clab.yml"), Path.cwd(), {})

        with patch("engulf_clab_freeze.plugin.run_freeze_command") as command:
            result = FreezePlugin().before_goal(invocation, api)

        self.assertIsNone(result)
        command.assert_not_called()
        api.state.assert_not_called()
        api.leases.assert_not_called()
        self.assertNotIn(call(SCHEMA_SOURCE_CONTEXT), api.get_context.call_args_list)
        self.assertNotIn(
            call(SCHEMA_VRNETLAB_SOURCE_CONTEXT), api.get_context.call_args_list
        )

    def test_help_lists_both_control_commands(self) -> None:
        help_text = FreezePlugin().help(MagicMock())

        self.assertIn("freeze [LAB_DIR | -t TOPOLOGY]", help_text)
        self.assertIn("runtime/, lab.tgz, and defrost.sh", help_text)
        self.assertIn("defrost ARCHIVE", help_text)

    def test_freeze_priority_precedes_every_other_bundled_plugin(self) -> None:
        self.assertGreater(FreezePlugin.priority, 110)


if __name__ == "__main__":
    unittest.main()
