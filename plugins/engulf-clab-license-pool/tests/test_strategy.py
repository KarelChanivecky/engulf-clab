from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from engulf_api import (
    ApplicationMetadata,
    BeforeGoalAPI,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_lab_parser import TOPOLOGY_CONTEXT, TopologySession
from engulf_clab_license_pool.plugin import (
    _STATE_VERSION,
    AUTO_LICENSE,
    DEFAULT_LICENSE_KIND,
    DISABLE_AUTO_LICENSE_ENVIRONMENT,
    INIT_LICENSE_POOL_COMMAND,
    LICENSE_POOL_STRATEGY_ENVIRONMENT,
    LICENSE_SELECTION_CONTEXT,
    PLUGIN_SCHEMA,
    UUID_ENVIRONMENT,
    LicensePoolError,
    LicensePoolPlugin,
    LicenseSelection,
    LicenseStrategy,
    _automatic_requests,
    _AutomaticRequest,
    _claim,
    _claim_all_with_created,
    _license_strategy,
    _parse_init_license_pool,
    _prompt_requests,
    _register_pool,
    _registered_pools,
    _release_workspace,
    _requests,
    _warn_legacy_uuid,
    license_contract,
)
from engulf_clab_schema_api import OptionKind, register_schema_arguments
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    ArgumentRegistry,
    BeforeCallEvent,
    CallMode,
    CallOutcome,
    CompletionContext,
    OutcomeKind,
    PreparationFailedEvent,
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

        auto_runtime = next(
            option
            for option in options
            if option.kind is OptionKind.RUNTIME_VAR and option.name == AUTO_LICENSE
        )
        auto_flag = next(
            option
            for option in options
            if option.kind is OptionKind.CLI_FLAG
            and option.name == "--eclab-auto-license"
        )
        self.assertEqual(auto_runtime.default_json, "false")
        self.assertEqual(auto_flag.environment, AUTO_LICENSE)

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
            self.assertEqual(registry["version"], 3)
            self.assertEqual(registry["registrations"], [])
            self.assertEqual(entry["last_used"][str(first)], 0)
            self.assertGreater(entry["last_used"][str(second)], 0)


class RegisteredLicensePoolTestCase(unittest.TestCase):
    _APPLICATION = ApplicationMetadata(
        application_id="engulf-clab",
        display_name="eclab",
        vendor="Engulf",
        product="eclab",
        short_product_name="eclab",
        version="1.0",
    )

    def test_schema_declares_init_command_and_auto_controls(self) -> None:
        options = PLUGIN_SCHEMA.snapshot(self._APPLICATION).options
        declared = {(option.kind, option.name, option.command) for option in options}
        self.assertIn((OptionKind.COMMAND, INIT_LICENSE_POOL_COMMAND, None), declared)
        self.assertIn(
            (OptionKind.CLI_ARGUMENT, "PATH", INIT_LICENSE_POOL_COMMAND), declared
        )
        self.assertIn(
            (OptionKind.CLI_FLAG, "--kind", INIT_LICENSE_POOL_COMMAND), declared
        )
        self.assertIn(
            (OptionKind.NODE_VAR, DISABLE_AUTO_LICENSE_ENVIRONMENT, None), declared
        )

    def test_init_command_defaults_and_persists_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = MemoryState()
            api = Mock(spec=BeforeGoalAPI)
            api.application = self._APPLICATION
            api.state.return_value = state
            api.leases.return_value = nullcontext()
            api.get_context.return_value = None
            contexts: dict[str, object] = {}
            api.set_context.side_effect = lambda key, value, **kwargs: (
                contexts.__setitem__(key, value)
            )

            result = LicensePoolPlugin().before_goal(
                Invocation((INIT_LICENSE_POOL_COMMAND,), root, {}), api
            )

            self.assertIsNone(result)
            self.assertEqual(
                [(entry.path, entry.kind) for entry in _registered_pools(state)],
                [(str(root.resolve()), DEFAULT_LICENSE_KIND)],
            )
            analyze_api = Mock(spec=InvocationAPI)
            analyze_api.require_context.side_effect = contexts.__getitem__
            contribution = LicensePoolPlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    (INIT_LICENSE_POOL_COMMAND,),
                    CallMode.NORMAL,
                ),
                analyze_api,
            )
            self.assertIsNotNone(contribution)
            assert contribution is not None
            self.assertEqual(contribution.preempt_exit_code, 0)

    def test_failed_init_is_deferred_to_wrapper_preemption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contexts: dict[str, object] = {}
            before_api = Mock(spec=BeforeGoalAPI)
            before_api.application = self._APPLICATION
            before_api.get_context.return_value = None
            before_api.set_context.side_effect = lambda key, value, **kwargs: (
                contexts.__setitem__(key, value)
            )

            result = LicensePoolPlugin().before_goal(
                Invocation(
                    (INIT_LICENSE_POOL_COMMAND, str(root / "missing")), root, {}
                ),
                before_api,
            )

            self.assertIsNone(result)
            analyze_api = Mock(spec=InvocationAPI)
            analyze_api.require_context.side_effect = contexts.__getitem__
            contribution = LicensePoolPlugin().analyze_call(
                BeforeCallEvent(
                    "containerlab",
                    (INIT_LICENSE_POOL_COMMAND, str(root / "missing")),
                    CallMode.NORMAL,
                ),
                analyze_api,
            )
            self.assertIsNotNone(contribution)
            assert contribution is not None
            self.assertEqual(contribution.preempt_exit_code, 2)

    def test_registration_order_update_and_missing_pool_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            state = MemoryState()

            self.assertTrue(_register_pool(state, first, DEFAULT_LICENSE_KIND))
            self.assertTrue(_register_pool(state, second, "linux"))
            self.assertFalse(_register_pool(state, first, "nokia_srlinux"))
            first.rmdir()

            registrations = _registered_pools(state)
            self.assertEqual(
                [(entry.path, entry.kind) for entry in registrations],
                [(str(second.resolve()), "linux")],
            )
            stored = json.loads(state.content["license-pools.json"])
            self.assertEqual(
                stored["registrations"],
                [{"kind": "linux", "path": str(second.resolve())}],
            )

    def test_parser_resolves_relative_path_and_rejects_invalid_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool, kind = _parse_init_license_pool(
                (".", "--kind=fortinet_fortigate"), root
            )
            self.assertEqual(pool, root.resolve())
            self.assertEqual(kind, DEFAULT_LICENSE_KIND)
            with self.assertRaisesRegex(LicensePoolError, "lowercase"):
                _parse_init_license_pool(("--kind", "FortiGate"), root)

    def test_parser_ignores_unclaimed_extension_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool, kind = _parse_init_license_pool(
                (
                    "--future-option",
                    ".",
                    "extension-positional",
                    "--future-option=value",
                    "--kind",
                    "linux",
                ),
                root,
            )

            self.assertEqual(pool, root.resolve())
            self.assertEqual(kind, "linux")


class AutomaticLicensePoolTestCase(unittest.TestCase):
    _APPLICATION = RegisteredLicensePoolTestCase._APPLICATION

    def _contract(self):
        return license_contract(self._APPLICATION)

    @staticmethod
    def _document(license_value: str, *, kind: str = DEFAULT_LICENSE_KIND, **env):
        return {
            "topology": {
                "nodes": {
                    "router": {
                        "kind": kind,
                        "license": license_value,
                        "env": env,
                    }
                }
            }
        }

    def test_unresolved_variable_uses_matching_registered_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            state = MemoryState()
            _register_pool(state, pool, DEFAULT_LICENSE_KIND)

            requests = _automatic_requests(
                self._document("$UNDEFINED_POOL"),
                {},
                Path("/workspace"),
                self._contract(),
                _registered_pools(state),
            )

            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].pools, (str(pool.resolve()),))

    def test_disable_only_blocks_implicit_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            state = MemoryState()
            _register_pool(state, pool, DEFAULT_LICENSE_KIND)
            registered = _registered_pools(state)
            disabled = {DISABLE_AUTO_LICENSE_ENVIRONMENT: "true"}

            self.assertEqual(
                _automatic_requests(
                    self._document("$UNDEFINED_POOL", **disabled),
                    {},
                    Path("/workspace"),
                    self._contract(),
                    registered,
                ),
                [],
            )
            self.assertEqual(
                len(
                    _automatic_requests(
                        self._document(AUTO_LICENSE, **disabled),
                        {},
                        Path("/workspace"),
                        self._contract(),
                        registered,
                    )
                ),
                1,
            )

    def test_variable_expression_used_as_a_path_does_not_trigger_fallback(self) -> None:
        self.assertEqual(
            _automatic_requests(
                self._document("${POOL}/router.lic"),
                {},
                Path("/workspace"),
                self._contract(),
                (),
            ),
            [],
        )

    def test_registered_pool_rejects_a_mismatched_explicit_node_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            state = MemoryState()
            _register_pool(state, pool, DEFAULT_LICENSE_KIND)
            with self.assertRaisesRegex(LicensePoolError, "does not match"):
                _requests(
                    self._document(str(pool), kind="linux"),
                    {},
                    Path("/workspace"),
                    self._contract(),
                    registered=_registered_pools(state),
                )

    def test_first_registered_pool_with_capacity_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "one.lic").write_text("first", encoding="utf-8")
            (second / "two.lic").write_text("second", encoding="utf-8")
            state = MemoryState()
            _claim(state, [_request(first, "/occupied")])
            automatic = [
                _AutomaticRequest(
                    "router",
                    (str(first.resolve()), str(second.resolve())),
                    None,
                    "/workspace:router",
                )
            ]

            assigned, _created = _claim_all_with_created(state, [], automatic)

            self.assertEqual(
                Path(assigned["/workspace:router"]).parent, second.resolve()
            )

    def test_missing_matching_registration_is_an_error(self) -> None:
        with self.assertRaisesRegex(LicensePoolError, "no registered license pool"):
            _automatic_requests(
                self._document(AUTO_LICENSE),
                {},
                Path("/workspace"),
                self._contract(),
                (),
            )

    def test_prepare_allocates_auto_marker_from_registered_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "lab"
            workspace.mkdir()
            pool = root / "pool"
            pool.mkdir()
            (pool / "router.lic").write_text("license", encoding="utf-8")
            state = MemoryState()
            _register_pool(state, pool, DEFAULT_LICENSE_KIND)
            session = TopologySession(
                workspace / "lab.clab.yml",
                self._document(AUTO_LICENSE),
            )
            contexts: dict[str, object] = {}
            api = Mock(spec=InvocationAPI)
            api.application = self._APPLICATION
            api.require_context.return_value = session
            api.state.side_effect = lambda scope: (
                SimpleNamespace(root=workspace)
                if scope is StateScope.WORKSPACE
                else state
            )
            api.leases.return_value = nullcontext()
            api.set_context.side_effect = lambda key, value: contexts.__setitem__(
                key, value
            )
            api.get_context.side_effect = lambda key, default=None: contexts.get(
                key, default
            )

            LicensePoolPlugin().prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    ("deploy",),
                    ("deploy", "-t", str(session.path)),
                    CallMode.NORMAL,
                    {},
                ),
                api,
            )

            registry = json.loads(state.content["license-pools.json"])
            self.assertEqual(
                len(registry["pools"][str(pool.resolve())]["allocations"]), 1
            )
            self.assertEqual(
                [
                    path.name
                    for path in (workspace / ".eclab" / "licenses").rglob("*.lic")
                ],
                ["router.lic"],
            )


class LicenseSelectionLoggingTestCase(unittest.TestCase):
    def test_prepare_logs_node_basename_and_pool(self) -> None:
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
                        "selected license basename=%r from pool=%r for node=%r",
                        "pooled.lic",
                        str(pool.resolve()),
                        "pooled",
                    ),
                    call(
                        "selected license basename=%r from pool=%r for node=%r",
                        "direct.lic",
                        None,
                        "direct",
                    ),
                ],
            )


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

    def test_unsuccessful_call_outcomes_roll_back_new_claim_and_copy(
        self,
    ) -> None:
        outcomes = (
            CallOutcome(OutcomeKind.COMPLETED, 70, process_started=True),
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
                    {"topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}},
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

    def test_later_preparation_failure_rolls_back_new_claim_and_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "lab"
            workspace.mkdir()
            pool = root / "pool"
            pool.mkdir()
            (pool / "router.lic").write_text("license", encoding="utf-8")
            session = TopologySession(
                workspace / "lab.clab.yml",
                {"topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}},
            )
            state = MemoryState()
            api, _contexts = self._api(session, state, workspace)
            environment = {"ROUTER_POOL": str(pool)}
            plugin = LicensePoolPlugin()
            wrapper_args = ("deploy",)
            effective_args = ("deploy", "-t", str(session.path))

            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab",
                    wrapper_args,
                    effective_args,
                    CallMode.NORMAL,
                    environment,
                ),
                api,
            )
            plugin.prepare_failed(
                PreparationFailedEvent(
                    "containerlab",
                    wrapper_args,
                    effective_args,
                    CallMode.NORMAL,
                    "later plugin failed",
                    failed_plugin_id="engulf_clab.lab_writer",
                    environment=environment,
                ),
                api,
            )

            registry = json.loads(state.content["license-pools.json"])
            self.assertEqual(registry["pools"][str(pool.resolve())]["allocations"], {})
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
                {"topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}},
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
            self.assertEqual(registry["pools"][str(pool.resolve())]["allocations"], {})
            self.assertEqual(
                list((workspace / ".eclab" / "licenses").rglob("*.lic")), []
            )

    def test_interrupt_rolls_back_before_propagating(self) -> None:
        """Ctrl-C during this plugin's own prepare_call must not strand a claim.

        An interrupt unwinds every plugin that prepared before this one, but the
        plugin that raised never receives prepare_failed. The except BaseException
        handler in prepare_call is the only thing releasing this attempt's claim, and an
        interrupt is not an Exception, so narrowing it leaks one license per
        interrupted deploy.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "lab"
            workspace.mkdir()
            pool = root / "pool"
            pool.mkdir()
            (pool / "router.lic").write_text("license", encoding="utf-8")
            session = TopologySession(
                workspace / "lab.clab.yml",
                {"topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}},
            )
            state = MemoryState()
            api, _contexts = self._api(session, state, workspace)

            with (
                patch(
                    "engulf_clab_license_pool.plugin.shutil.copy2",
                    side_effect=KeyboardInterrupt(),
                ),
                self.assertRaises(KeyboardInterrupt),
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
            self.assertEqual(registry["pools"][str(pool.resolve())]["allocations"], {})
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
                {"topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}},
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


class DestroyAllCleanupTestCase(unittest.TestCase):
    """`destroy --all` must clear the registry *and* every workspace's copies."""

    @staticmethod
    def _destroy(*args: str) -> AfterCallEvent:
        wrapper_args = ("destroy", *args)
        return AfterCallEvent(
            binary="containerlab",
            wrapper_args=wrapper_args,
            effective_args=wrapper_args,
            mode=CallMode.NORMAL,
            outcome=CallOutcome(OutcomeKind.COMPLETED, 0, process_started=True),
            duration_seconds=0.1,
        )

    def _api(self, user_state: MemoryState, workspace: Path) -> Mock:
        api = Mock(spec=InvocationAPI)
        api.application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="eclab",
            vendor="Engulf",
            product="eclab",
            short_product_name="eclab",
            version="1.0",
        )
        api.state.side_effect = lambda scope: (
            SimpleNamespace(root=workspace)
            if scope is StateScope.WORKSPACE
            else user_state
        )
        api.lease.return_value = nullcontext()
        api.leases.return_value = nullcontext()
        return api

    def _seed(self, root: Path, pool: Path, names: tuple[str, ...]) -> MemoryState:
        """Claim one license per workspace and place its copy on disk."""
        state = MemoryState()
        allocations = {}
        for name in names:
            workspace = root / name
            copies = workspace / ".eclab" / "licenses"
            copies.mkdir(parents=True)
            (copies / "router.lic").write_text("license", encoding="utf-8")
            allocations[str(pool / f"{name}.lic")] = f"{workspace}:router"
        state.content["license-pools.json"] = json.dumps(
            {
                "version": _STATE_VERSION,
                "pools": {
                    str(pool): {
                        "allocations": allocations,
                        "history": {},
                        "clamped": [],
                        "last_used": {},
                        "round_robin_index": 0,
                        "usage_sequence": 0,
                    },
                },
                "registrations": [],
            }
        )
        return state

    def test_destroy_all_removes_copies_from_every_claimed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root / "pool"
            pool.mkdir()
            state = self._seed(root, pool, ("first", "second"))
            api = self._api(state, root / "first")

            LicensePoolPlugin().after_call(self._destroy("--all"), api)

            registry = json.loads(state.content["license-pools.json"])
            self.assertEqual(registry["pools"][str(pool)]["allocations"], {})
            for name in ("first", "second"):
                self.assertFalse(
                    (root / name / ".eclab" / "licenses").exists(),
                    f"{name} kept its copied licenses",
                )

    def test_ordinary_destroy_only_touches_the_current_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root / "pool"
            pool.mkdir()
            state = self._seed(root, pool, ("first", "second"))
            api = self._api(state, root / "first")

            LicensePoolPlugin().after_call(self._destroy(), api)

            self.assertFalse((root / "first" / ".eclab" / "licenses").exists())
            self.assertTrue(
                (root / "second" / ".eclab" / "licenses").exists(),
                "an unrelated workspace lost its copied licenses",
            )


class AllocationIdentityTestCase(unittest.TestCase):
    """Identity rides on node `env`, which Containerlab's own schema accepts.

    A top-level `uuid:` node field is not part of the Containerlab schema, so a
    topology carrying one is rejected by every subcommand that validates the raw
    document even though deploy accepted it.
    """

    _APPLICATION = ApplicationMetadata(
        application_id="engulf-clab",
        display_name="eclab",
        vendor="Engulf",
        product="eclab",
        short_product_name="eclab",
        version="1.0",
    )

    def test_schema_declares_no_node_level_uuid_property(self) -> None:
        options = PLUGIN_SCHEMA.snapshot(self._APPLICATION).options
        properties = {o.name for o in options if o.kind is OptionKind.PROPERTY}
        variables = {o.name for o in options if o.kind is OptionKind.NODE_VAR}

        self.assertNotIn("uuid", properties)
        self.assertIn("FOS_UUID", variables)

    def test_identity_comes_from_the_node_environment(self) -> None:
        topology = {
            "topology": {
                "nodes": {
                    "router": {
                        "license": "$ROUTER_POOL",
                        "env": {"FOS_UUID": "stable-identity"},
                    }
                }
            }
        }
        contract = license_contract(self._APPLICATION)

        with tempfile.TemporaryDirectory() as pool:
            requests = _requests(topology, {"ROUTER_POOL": pool}, Path("/ws"), contract)

        self.assertEqual(
            [claim for _n, _p, _c, claim in requests], ["/ws:stable-identity"]
        )

    def test_identity_falls_back_to_the_node_name(self) -> None:
        topology = {"topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}}
        contract = license_contract(self._APPLICATION)

        with tempfile.TemporaryDirectory() as pool:
            requests = _requests(topology, {"ROUTER_POOL": pool}, Path("/ws"), contract)

        self.assertEqual([claim for _n, _p, _c, claim in requests], ["/ws:router"])


class PoolReferenceTestCase(unittest.TestCase):
    """The parser expands `$POOL` before this plugin reads the topology.

    engulf_clab.lab_parser renders Containerlab environment expressions while
    loading the topology, so a node written as `license: $POOL` reaches
    prepare_call as the pool directory path. Recognising only a leading `$`
    left those nodes unclaimed and handed Containerlab a directory where it
    expects a license file.
    """

    _APPLICATION = ApplicationMetadata(
        application_id="engulf-clab",
        display_name="eclab",
        vendor="Engulf",
        product="eclab",
        short_product_name="eclab",
        version="1.0",
    )

    def _requests_for(self, license_value: str, environ: dict[str, str]):
        topology = {"topology": {"nodes": {"router": {"license": license_value}}}}
        return _requests(
            topology, environ, Path("/ws"), license_contract(self._APPLICATION)
        )

    def test_an_expanded_pool_directory_is_still_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as pool:
            requests = self._requests_for(pool, {"ROUTER_POOL": pool})

            self.assertEqual(
                requests, [("router", str(Path(pool).resolve()), None, "/ws:router")]
            )

    def test_an_unexpanded_reference_is_reserved_for_automatic_selection(self) -> None:
        self.assertEqual(self._requests_for("$ROUTER_POOL", {}), [])

    def test_a_braced_reference_resolves_to_its_pool(self) -> None:
        with tempfile.TemporaryDirectory() as pool:
            requests = self._requests_for("${ROUTER_POOL}", {"ROUTER_POOL": pool})

            self.assertEqual(
                [path for _n, path, _c, _claim in requests], [str(Path(pool).resolve())]
            )

    def test_a_license_file_is_left_to_containerlab(self) -> None:
        with tempfile.TemporaryDirectory() as pool:
            licence = Path(pool) / "router.lic"
            licence.write_text("key", encoding="utf-8")

            self.assertEqual(self._requests_for(str(licence), {}), [])

    def test_a_frozen_prompt_marker_is_not_a_pool(self) -> None:
        marker = license_contract(self._APPLICATION).prompt_marker

        self.assertEqual(self._requests_for(marker, {}), [])

    def test_missing_null_and_empty_license_values_are_not_pools(self) -> None:
        contract = license_contract(self._APPLICATION)

        for description, node in (
            ("missing", {}),
            ("null", {"license": None}),
            ("empty", {"license": ""}),
        ):
            with self.subTest(description=description):
                topology = {"topology": {"nodes": {"router": node}}}
                self.assertEqual(_requests(topology, {}, Path("/ws"), contract), [])

    def test_a_path_that_does_not_exist_is_left_to_containerlab(self) -> None:
        self.assertEqual(self._requests_for("/nonexistent/pool/FGT", {}), [])


class InheritedTopologyRequestTestCase(unittest.TestCase):
    _APPLICATION = ApplicationMetadata(
        application_id="engulf-clab",
        display_name="eclab",
        vendor="Engulf",
        product="eclab",
        short_product_name="eclab",
        version="1.0",
    )

    def _document(self, level: str, definition: dict[str, object]) -> dict[str, object]:
        node: dict[str, object] = {"kind": "linux", "group": "clients"}
        topology: dict[str, object] = {"nodes": {"router": node}}
        if level == "defaults":
            topology[level] = definition
        elif level == "nodes":
            node.update(definition)
        else:
            topology[level] = {"linux" if level == "kinds" else "clients": definition}
        return {"topology": topology}

    def test_pool_and_reserved_environment_values_inherit_at_every_level(self) -> None:
        contract = license_contract(self._APPLICATION)
        with tempfile.TemporaryDirectory() as directory:
            for level in ("defaults", "kinds", "groups", "nodes"):
                with self.subTest(level=level):
                    document = self._document(
                        level,
                        {
                            "license": "$ROUTER_POOL",
                            "env": {
                                contract.clamp_environment: "serial-0001.lic",
                                UUID_ENVIRONMENT: "stable-router",
                            },
                        },
                    )
                    requests = _requests(
                        document,
                        {"ROUTER_POOL": directory},
                        Path("/workspace"),
                        contract,
                    )
                    self.assertEqual(
                        requests,
                        [
                            (
                                "router",
                                str(Path(directory).resolve()),
                                "serial-0001.lic",
                                "/workspace:stable-router",
                            )
                        ],
                    )

    def test_frozen_prompt_and_identity_inherit_from_kind(self) -> None:
        contract = license_contract(self._APPLICATION)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "router.lic"
            source.write_text("license", encoding="utf-8")
            document = self._document(
                "kinds",
                {
                    "license": contract.prompt_marker,
                    "env": {UUID_ENVIRONMENT: "stable-router"},
                },
            )
            pools, direct, automatic = _prompt_requests(
                document,
                {contract.node_license_environment("router"): str(source)},
                Path(directory),
                contract,
            )
            self.assertEqual(pools, [])
            self.assertEqual(automatic, ())
            self.assertEqual(
                direct["router"], (f"{directory}:stable-router", str(source))
            )


class LegacyUuidWarningTestCase(unittest.TestCase):
    def test_a_topology_still_using_uuid_is_named_in_a_warning(self) -> None:
        api = Mock(spec=InvocationAPI)
        topology = {
            "topology": {
                "nodes": {
                    "router": {"uuid": "old-identity"},
                    "switch": {"env": {"FOS_UUID": "new-identity"}},
                }
            }
        }

        _warn_legacy_uuid(api, topology)

        api.logger.warning.assert_called_once()
        message = api.logger.warning.call_args.args
        self.assertIn("router", message[1])
        self.assertNotIn("switch", message[1])
        self.assertEqual(message[2], "FOS_UUID")

    def test_a_migrated_topology_warns_about_nothing(self) -> None:
        api = Mock(spec=InvocationAPI)

        _warn_legacy_uuid(
            api, {"topology": {"nodes": {"router": {"env": {"FOS_UUID": "x"}}}}}
        )

        api.logger.warning.assert_not_called()


class LicenseSelectionContextTestCase(unittest.TestCase):
    def _prepare(self, root: Path) -> tuple[Mock, TopologySession]:
        lab = root / "lab"
        lab.mkdir()
        pool = root / "pool"
        pool.mkdir()
        (pool / "pooled.lic").write_text("pool", encoding="utf-8")
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
        store: dict[str, object] = {}
        api.set_context.side_effect = store.__setitem__
        api.get_context.side_effect = lambda context_id: store.get(context_id)
        workspace_state = SimpleNamespace(root=lab)
        user_state = MemoryState()
        api.state.side_effect = lambda scope: (
            workspace_state if scope is StateScope.WORKSPACE else user_state
        )
        api.leases.return_value = nullcontext()
        event = PreparedCallEvent(
            "containerlab",
            ("deploy",),
            ("deploy", "-t", str(session.path)),
            CallMode.NORMAL,
            {"ROUTER_POOL": str(pool), "ECLAB_LICENSE_DIRECT": str(direct_license)},
        )
        LicensePoolPlugin().prepare_call(event, api)
        return api, session

    def _published(self, api: Mock) -> dict[str, LicenseSelection]:
        for entry in api.set_context.call_args_list:
            if entry.args[0] == LICENSE_SELECTION_CONTEXT:
                return dict(entry.args[1])
        raise AssertionError("selection context was never published")

    def test_selection_distinguishes_pooled_from_directly_named_licenses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api, _session = self._prepare(root)

            published = self._published(api)

            self.assertEqual(set(published), {"pooled", "direct"})
            pooled = published["pooled"]
            self.assertTrue(pooled.from_pool)
            self.assertEqual(pooled.pool, str(root / "pool"))
            self.assertEqual(pooled.source_name, "pooled.lic")
            # A directly named license has no pool, which is the distinction an
            # edition-specific plugin branches on.
            direct = published["direct"]
            self.assertFalse(direct.from_pool)
            self.assertIsNone(direct.pool)
            self.assertEqual(direct.source_name, "direct.lic")

    def test_selection_survives_as_a_read_only_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api, _session = self._prepare(Path(directory))
            payload = next(
                entry.args[1]
                for entry in api.set_context.call_args_list
                if entry.args[0] == LICENSE_SELECTION_CONTEXT
            )
            with self.assertRaises(TypeError):
                payload["pooled"] = None  # type: ignore[index]

    def test_publishing_reads_the_context_back_and_keeps_paths_out_of_logs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api, _session = self._prepare(root)

            # The read happens at the point of publication, so every path that
            # publishes also consumes -- an edition shipping no reader for this
            # extension point never trips the unread-context warning.
            self.assertIn(
                call(LICENSE_SELECTION_CONTEXT), api.get_context.call_args_list
            )
            rendered = repr(api.logger.debug.call_args_list)
            self.assertIn("pooled.lic", rendered)
            self.assertNotIn(str(root), rendered)


class LicensePoolEntryFilterTestCase(unittest.TestCase):
    def test_dotfiles_are_never_selected_from_a_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            (pool / "real.lic").write_text("real", encoding="utf-8")
            # The kind of debris a shared pool directory accumulates.
            for name in (".hidden.lic", ".DS_Store", ".real.lic.swp"):
                (pool / name).write_text("not a license", encoding="utf-8")
            state = MemoryState()
            workspace = "/labs/dotfiles"

            assigned = _claim(
                state,
                [_request(pool, workspace)],
                LicenseStrategy.LEAST_RECENTLY_USED,
            )

            self.assertEqual(_filename(assigned, workspace), "real.lic")

    def test_pool_of_only_dotfiles_reports_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            (pool / ".hidden.lic").write_text("hidden", encoding="utf-8")
            state = MemoryState()

            with self.assertRaisesRegex(LicensePoolError, "license pool is empty"):
                _claim(
                    state,
                    [_request(pool, "/labs/only-dotfiles")],
                    LicenseStrategy.LEAST_RECENTLY_USED,
                )

    def test_dotfile_symlink_to_a_real_license_is_still_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root / "pool"
            pool.mkdir()
            target = root / "elsewhere.lic"
            target.write_text("real", encoding="utf-8")
            # Filtering happens on the pool entry's name, before resolving.
            (pool / ".link.lic").symlink_to(target)
            state = MemoryState()

            with self.assertRaisesRegex(LicensePoolError, "license pool is empty"):
                _claim(
                    state,
                    [_request(pool, "/labs/symlink")],
                    LicenseStrategy.LEAST_RECENTLY_USED,
                )

    def test_empty_files_remain_skipped_alongside_dotfiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            (pool / "touched.tst").write_text("", encoding="utf-8")
            (pool / "real.lic").write_text("real", encoding="utf-8")
            state = MemoryState()
            workspace = "/labs/empty"

            assigned = _claim(
                state,
                [_request(pool, workspace)],
                LicenseStrategy.LEAST_RECENTLY_USED,
            )

            self.assertEqual(_filename(assigned, workspace), "real.lic")

    def test_clamping_to_a_dotfile_fails_rather_than_selecting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            (pool / "real.lic").write_text("real", encoding="utf-8")
            (pool / ".hidden.lic").write_text("hidden", encoding="utf-8")
            state = MemoryState()
            request = (
                "router",
                str(pool.resolve()),
                ".hidden.lic",
                "/labs/clamp:router",
            )

            with self.assertRaisesRegex(
                LicensePoolError, "clamped license is unavailable"
            ):
                _claim(state, [request], LicenseStrategy.LEAST_RECENTLY_USED)
