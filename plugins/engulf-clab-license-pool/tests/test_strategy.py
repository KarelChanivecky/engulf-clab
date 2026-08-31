from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from engulf_api import ApplicationMetadata, InvocationAPI, StateScope
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_clab_license_pool.plugin import (
    LICENSE_POOL_STRATEGY_ENVIRONMENT,
    PLUGIN_SCHEMA,
    LicensePoolError,
    LicensePoolPlugin,
    LicenseStrategy,
    _claim,
    _license_strategy,
    _release_workspace,
)
from engulf_clab_schema_api import OptionKind, register_schema_arguments
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    ArgumentRegistry,
    CallMode,
    CallOutcome,
    CompletionContext,
    OutcomeKind,
    PreparedCallEvent,
    Shell,
    invoke_provider,
    normalize_candidate,
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


def _request(pool: Path, workspace: str) -> tuple[str, str, None, str]:
    return ("router", str(pool.resolve()), None, f"{workspace}:router")


def _filename(assignments: dict[str, str], workspace: str) -> str:
    return Path(assignments[f"{workspace}:router"]).name


class LicenseStrategyTestCase(unittest.TestCase):
    def test_schema_declares_closed_strategy_flag_and_environment_default(self) -> None:
        application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="eclab",
            vendor="Engulf",
            product="eclab",
            short_product_name="eclab",
            version="1.0",
        )
        options = PLUGIN_SCHEMA.options(application)
        runtime = next(
            option
            for option in options
            if option.kind is OptionKind.RUNTIME_VAR
            and option.name == LICENSE_POOL_STRATEGY_ENVIRONMENT
        )
        flag = next(
            option
            for option in options
            if option.kind is OptionKind.CLI_FLAG
            and option.name == "--eclab-license-pool-strategy"
        )
        expected = ("sticky", "round-robin", "least-recently-used")
        self.assertEqual(runtime.values, expected)
        self.assertEqual(runtime.default_json, '"least-recently-used"')
        self.assertEqual(flag.values, expected)
        self.assertEqual(flag.default_json, '"least-recently-used"')
        self.assertEqual(flag.environment, LICENSE_POOL_STRATEGY_ENVIRONMENT)

        registry = ArgumentRegistry()
        register_schema_arguments(registry, PLUGIN_SCHEMA, application)
        registered = registry.find_exact("--eclab-license-pool-strategy")
        self.assertIsNotNone(registered)
        assert registered is not None
        self.assertEqual(registered.environment, LICENSE_POOL_STRATEGY_ENVIRONMENT)
        self.assertIsNotNone(registered.value_completer)
        assert registered.value_completer is not None
        context = CompletionContext(
            Shell.BASH,
            "eclab",
            "containerlab",
            ("deploy", "--eclab-license-pool-strategy", ""),
            2,
        )
        candidates = [
            normalize_candidate(candidate).value
            for candidate in invoke_provider(registered.value_completer, context)
        ]
        self.assertEqual(candidates, list(expected))

    def test_strategy_defaults_to_lru_and_rejects_unknown_values(self) -> None:
        self.assertIs(_license_strategy({}), LicenseStrategy.LEAST_RECENTLY_USED)
        self.assertIs(
            _license_strategy(
                {LICENSE_POOL_STRATEGY_ENVIRONMENT: "least-recently-used"}
            ),
            LicenseStrategy.LEAST_RECENTLY_USED,
        )
        with self.assertRaisesRegex(
            LicensePoolError,
            "sticky, round-robin, least-recently-used",
        ):
            _license_strategy({LICENSE_POOL_STRATEGY_ENVIRONMENT: "random"})

    def test_active_claim_stays_sticky_for_every_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            for name in ("b.lic", "a.lic"):
                (pool / name).write_text(name, encoding="utf-8")
            state = MemoryState()
            workspace = "/labs/one"
            first = _claim(
                state,
                [_request(pool, workspace)],
                LicenseStrategy.ROUND_ROBIN,
            )
            second = _claim(
                state,
                [_request(pool, workspace)],
                LicenseStrategy.LEAST_RECENTLY_USED,
            )
            self.assertEqual(first, second)

    def test_sticky_reuses_historical_claim_before_never_used_license(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            for name in ("a.lic", "b.lic"):
                (pool / name).write_text(name, encoding="utf-8")
            state = MemoryState()
            workspace = "/labs/sticky"

            first = _claim(
                state,
                [_request(pool, workspace)],
                LicenseStrategy.STICKY,
            )
            _release_workspace(state, workspace)
            second = _claim(
                state,
                [_request(pool, workspace)],
                LicenseStrategy.STICKY,
            )

            self.assertEqual(_filename(first, workspace), "a.lic")
            self.assertEqual(second, first)

    def test_round_robin_advances_through_sorted_pool_indices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            for name in ("c.lic", "a.lic", "b.lic"):
                (pool / name).write_text(name, encoding="utf-8")
            state = MemoryState()
            selected: list[str] = []
            for index in range(4):
                workspace = f"/labs/{index}"
                assigned = _claim(
                    state,
                    [_request(pool, workspace)],
                    LicenseStrategy.ROUND_ROBIN,
                )
                selected.append(_filename(assigned, workspace))
                _release_workspace(state, workspace)
            self.assertEqual(selected, ["a.lic", "b.lic", "c.lic", "a.lic"])

    def test_least_recently_used_selects_the_oldest_available_license(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            for name in ("a.lic", "b.lic", "c.lic"):
                (pool / name).write_text(name, encoding="utf-8")
            state = MemoryState()

            active = ["/labs/a", "/labs/b", "/labs/c"]
            first = _claim(
                state,
                [_request(pool, workspace) for workspace in active],
                LicenseStrategy.STICKY,
            )
            self.assertEqual(
                [_filename(first, workspace) for workspace in active],
                ["a.lic", "b.lic", "c.lic"],
            )

            _release_workspace(state, active[0])
            refresh = "/labs/refresh"
            refreshed = _claim(
                state,
                [_request(pool, refresh)],
                LicenseStrategy.LEAST_RECENTLY_USED,
            )
            self.assertEqual(_filename(refreshed, refresh), "a.lic")
            _release_workspace(state, refresh)
            _release_workspace(state, active[1])
            _release_workspace(state, active[2])

            final = "/labs/final"
            assigned = _claim(
                state,
                [_request(pool, final)],
                LicenseStrategy.LEAST_RECENTLY_USED,
            )
            self.assertEqual(_filename(assigned, final), "b.lic")

    def test_automatic_strategies_avoid_historically_clamped_files(self) -> None:
        for strategy in (
            LicenseStrategy.ROUND_ROBIN,
            LicenseStrategy.LEAST_RECENTLY_USED,
        ):
            with (
                self.subTest(strategy=strategy),
                tempfile.TemporaryDirectory() as directory,
            ):
                pool = Path(directory)
                (pool / "a.lic").write_text("a", encoding="utf-8")
                (pool / "b.lic").write_text("b", encoding="utf-8")
                state = MemoryState()
                clamped_workspace = "/labs/clamped"
                clamped_request = (
                    "router",
                    str(pool.resolve()),
                    "a.lic",
                    f"{clamped_workspace}:router",
                )
                _claim(state, [clamped_request], strategy)
                _release_workspace(state, clamped_workspace)

                workspace = "/labs/automatic"
                assigned = _claim(state, [_request(pool, workspace)], strategy)
                self.assertEqual(_filename(assigned, workspace), "b.lic")

    def test_version_one_state_is_migrated_with_usage_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory).resolve()
            first = pool / "a.lic"
            second = pool / "b.lic"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")
            state = MemoryState()
            state.content["license-pools.json"] = json.dumps(
                {
                    "version": 1,
                    "pools": {
                        str(pool): {
                            "allocations": {},
                            "history": {str(first): "/labs/old:router"},
                            "clamped": [],
                        }
                    },
                }
            )

            workspace = "/labs/new"
            assigned = _claim(state, [_request(pool, workspace)])

            self.assertEqual(_filename(assigned, workspace), "b.lic")
            registry = json.loads(state.content["license-pools.json"])
            entry = registry["pools"][str(pool)]
            self.assertEqual(registry["version"], 2)
            self.assertEqual(entry["last_used"][str(first)], 0)
            self.assertGreater(entry["last_used"][str(second)], 0)


class LicenseSelectionLoggingTestCase(unittest.TestCase):
    def test_prepare_logs_node_and_basename_without_source_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lab = root / "lab"
            lab.mkdir()
            pool = root / "pool"
            pool.mkdir()
            pooled_license = pool / "pooled.lic"
            pooled_license.write_text("pool", encoding="utf-8")
            direct_license = root / "direct.lic"
            direct_license.write_text("direct", encoding="utf-8")
            document = {
                "topology": {
                    "nodes": {
                        "pooled": {"license": "$ROUTER_POOL"},
                        "direct": {"license": "__ECLAB_LICENSE_PROMPT__"},
                    }
                }
            }
            session = TopologySession(lab / "lab.clab.yml", document)
            user_state = MemoryState()
            workspace_state = SimpleNamespace(root=lab)
            api = Mock(spec=InvocationAPI)
            api.application = ApplicationMetadata(
                application_id="engulf-clab",
                display_name="eclab",
                vendor="Engulf",
                product="eclab",
                short_product_name="eclab",
                version="1.0",
            )
            api.require_context.return_value = session
            api.state.side_effect = lambda scope: (
                workspace_state if scope is StateScope.WORKSPACE else user_state
            )
            api.leases.return_value = nullcontext()
            event = PreparedCallEvent(
                "containerlab",
                ("deploy",),
                ("deploy", "-t", str(session.path)),
                CallMode.NORMAL,
                {
                    "ROUTER_POOL": str(pool),
                    "ECLAB_LICENSE_DIRECT": str(direct_license),
                },
            )

            LicensePoolPlugin().prepare_call(event, api)

            api.require_context.assert_called_with(TOPOLOGY_CONTEXT)
            self.assertEqual(
                api.logger.info.call_args_list,
                [
                    call(
                        "selected license basename=%r for node=%r",
                        "pooled.lic",
                        "pooled",
                    ),
                    call(
                        "selected license basename=%r for node=%r",
                        "direct.lic",
                        "direct",
                    ),
                ],
            )
            rendered_calls = repr(api.logger.info.call_args_list)
            self.assertNotIn(str(root), rendered_calls)


class LicenseDeployRollbackTestCase(unittest.TestCase):
    def _api(
        self,
        session: TopologySession,
        user_state: MemoryState,
        workspace: Path,
    ) -> tuple[Mock, dict[str, object]]:
        contexts: dict[str, object] = {}
        api = Mock(spec=InvocationAPI)
        api.application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="eclab",
            vendor="Engulf",
            product="eclab",
            short_product_name="eclab",
            version="1.0",
        )
        api.require_context.return_value = session
        api.state.side_effect = lambda scope: (
            SimpleNamespace(root=workspace)
            if scope is StateScope.WORKSPACE
            else user_state
        )
        api.leases.return_value = nullcontext()
        api.set_context.side_effect = lambda key, value: contexts.__setitem__(
            key, value
        )
        api.get_context.side_effect = lambda key, default=None: contexts.get(
            key, default
        )
        return api, contexts

    def test_failed_preempted_and_signaled_deploy_roll_back_new_claim_and_copy(
        self,
    ) -> None:
        outcomes = (
            CallOutcome(OutcomeKind.COMPLETED, 70, process_started=True),
            CallOutcome(
                OutcomeKind.FRAMEWORK_FAILED,
                70,
                process_started=False,
                error="later provider failed",
            ),
            CallOutcome(
                OutcomeKind.PREEMPTED,
                1,
                process_started=False,
                preempted_by="test",
            ),
            CallOutcome(
                OutcomeKind.SIGNALED,
                130,
                process_started=True,
                signal=2,
            ),
        )
        for outcome in outcomes:
            with (
                self.subTest(outcome=outcome.kind),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                workspace = root / "lab"
                workspace.mkdir()
                pool = root / "pool"
                pool.mkdir()
                (pool / "router.lic").write_text("license", encoding="utf-8")
                session = TopologySession(
                    workspace / "lab.clab.yml",
                    {
                        "topology": {
                            "nodes": {"router": {"license": "$ROUTER_POOL"}}
                        }
                    },
                )
                state = MemoryState()
                api, _contexts = self._api(session, state, workspace)
                environment = {"ROUTER_POOL": str(pool)}
                plugin = LicensePoolPlugin()

                plugin.prepare_call(
                    PreparedCallEvent(
                        "containerlab",
                        ("deploy",),
                        ("deploy", "-t", str(session.path)),
                        CallMode.NORMAL,
                        environment,
                    ),
                    api,
                )
                registry = json.loads(state.content["license-pools.json"])
                self.assertEqual(
                    len(registry["pools"][str(pool.resolve())]["allocations"]), 1
                )
                self.assertEqual(
                    len(list((workspace / ".eclab" / "licenses").rglob("*.lic"))),
                    1,
                )

                plugin.after_call(
                    AfterCallEvent(
                        "containerlab",
                        ("deploy",),
                        ("deploy", "-t", str(session.path)),
                        CallMode.NORMAL,
                        outcome,
                        0.1,
                        environment,
                    ),
                    api,
                )

                registry = json.loads(state.content["license-pools.json"])
                self.assertEqual(
                    registry["pools"][str(pool.resolve())]["allocations"], {}
                )
                self.assertEqual(
                    list((workspace / ".eclab" / "licenses").rglob("*.lic")), []
                )

    def test_prepare_exception_rolls_back_before_propagating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "lab"
            workspace.mkdir()
            pool = root / "pool"
            pool.mkdir()
            (pool / "router.lic").write_text("license", encoding="utf-8")
            session = TopologySession(
                workspace / "lab.clab.yml",
                {
                    "topology": {
                        "nodes": {"router": {"license": "$ROUTER_POOL"}}
                    }
                },
            )
            state = MemoryState()
            api, _contexts = self._api(session, state, workspace)

            with (
                patch(
                    "engulf_clab_license_pool.plugin.shutil.copy2",
                    side_effect=OSError("copy failed"),
                ),
                self.assertRaisesRegex(OSError, "copy failed"),
            ):
                LicensePoolPlugin().prepare_call(
                    PreparedCallEvent(
                        "containerlab",
                        ("deploy",),
                        ("deploy", "-t", str(session.path)),
                        CallMode.NORMAL,
                        {"ROUTER_POOL": str(pool)},
                    ),
                    api,
                )

            registry = json.loads(state.content["license-pools.json"])
            self.assertEqual(
                registry["pools"][str(pool.resolve())]["allocations"], {}
            )
            self.assertEqual(
                list((workspace / ".eclab" / "licenses").rglob("*.lic")), []
            )

    def test_failed_retry_preserves_preexisting_claim_and_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "lab"
            workspace.mkdir()
            pool = root / "pool"
            pool.mkdir()
            (pool / "router.lic").write_text("license", encoding="utf-8")
            session = TopologySession(
                workspace / "lab.clab.yml",
                {
                    "topology": {
                        "nodes": {"router": {"license": "$ROUTER_POOL"}}
                    }
                },
            )
            state = MemoryState()
            environment = {"ROUTER_POOL": str(pool)}
            event = PreparedCallEvent(
                "containerlab",
                ("deploy",),
                ("deploy", "-t", str(session.path)),
                CallMode.NORMAL,
                environment,
            )
            plugin = LicensePoolPlugin()

            first_api, _first_contexts = self._api(session, state, workspace)
            plugin.prepare_call(event, first_api)
            second_api, _second_contexts = self._api(session, state, workspace)
            plugin.prepare_call(event, second_api)
            plugin.after_call(
                AfterCallEvent(
                    "containerlab",
                    ("deploy",),
                    event.effective_args,
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 70, process_started=True),
                    0.1,
                    environment,
                ),
                second_api,
            )

            registry = json.loads(state.content["license-pools.json"])
            self.assertEqual(
                len(registry["pools"][str(pool.resolve())]["allocations"]), 1
            )
            self.assertEqual(
                len(list((workspace / ".eclab" / "licenses").rglob("*.lic"))),
                1,
            )


if __name__ == "__main__":
    unittest.main()
