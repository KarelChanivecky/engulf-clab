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
    _STATE_VERSION,
    LICENSE_POOL_STRATEGY_ENVIRONMENT,
    PLUGIN_SCHEMA,
    LicensePoolError,
    LicensePoolPlugin,
    LicenseStrategy,
    _claim,
    _license_strategy,
    _release_workspace,
    _requests,
    _warn_legacy_uuid,
    license_contract,
)
from engulf_clab_schema_api import OptionKind, register_schema_arguments
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    ArgumentRegistry,
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
            requests = _requests(
                topology, {"ROUTER_POOL": pool}, Path("/ws"), contract
            )

        self.assertEqual(
            [claim for _n, _p, _c, claim in requests], ["/ws:stable-identity"]
        )

    def test_identity_falls_back_to_the_node_name(self) -> None:
        topology = {
            "topology": {"nodes": {"router": {"license": "$ROUTER_POOL"}}}
        }
        contract = license_contract(self._APPLICATION)

        with tempfile.TemporaryDirectory() as pool:
            requests = _requests(
                topology, {"ROUTER_POOL": pool}, Path("/ws"), contract
            )

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

    def test_an_unexpanded_reference_still_names_the_missing_variable(self) -> None:
        with self.assertRaises(LicensePoolError) as raised:
            self._requests_for("$ROUTER_POOL", {})

        self.assertIn("$ROUTER_POOL is not set", str(raised.exception))

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

    def test_a_path_that_does_not_exist_is_left_to_containerlab(self) -> None:
        self.assertEqual(self._requests_for("/nonexistent/pool/FGT", {}), [])


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
