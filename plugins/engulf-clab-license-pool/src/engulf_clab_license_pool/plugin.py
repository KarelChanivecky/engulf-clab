from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from engulf_api import (
    ApplicationMetadata,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
)
from engulf_clab_lab_parser import (
    TOPOLOGY_CONTEXT,
    TopologyError,
    TopologySession,
    editor,
    effective_nodes,
    is_topology_mutation_command,
)
from engulf_clab_license_pool_api import (
    NO_DEFAULT,
    LicensePoolMetadataContext,
    LicensePoolMetadataContributor,
    LicensePoolMetadataError,
    LicensePoolVariable,
    LicensePoolVariableType,
    PoolMetadata,
    discover_metadata_contributors,
    format_license_pool_variable_value,
    load_pool_metadata,
    metadata_variables_for,
    parse_license_pool_variable_value,
    validate_contribution,
    validate_license_pool_variable_value,
)
from engulf_clab_license_pool_lib import (
    LICENSE_ALLOCATION_HANDOFF_CONTEXT,
    LICENSE_POOL_AVAILABILITY_CONTEXT,
    AllocationRequest,
    LicenseAllocationHandoff,
    LicensePoolAvailability,
    LicensePoolError,
    LicensePoolManager,
    LicenseStrategy,
    PoolManagerRequest,
    PoolState,
    coerce_strategy,
    publish_license_pool_availability,
    run_pool_managers,
)
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    ExplainedValue,
    LifecycleStage,
    PathBase,
    PluginSchema,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
    OutcomeKind,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from .selector import selector

_FILE = "license-pools.json"
_STATE_VERSION = 3
_INVOCATION_ALLOCATION_CONTEXT = "engulf_clab.license_pool.invocation_allocation"
_INIT_LICENSE_POOL_EXIT_CONTEXT = "engulf_clab.license_pool.init_exit"
_INSPECT_LICENSE_POOL_EXIT_CONTEXT = "engulf_clab.license_pool.inspect_exit"
INIT_LICENSE_POOL_CONTEXT = "engulf_clab.license_pool.init_registration"

# Published for plugins outside this package -- typically an edition-specific
# one that must reason about the license a node actually received, such as
# recognizing a file suffix this plugin has no opinion about. It is the only
# supported way to learn that: allocation state is plugin-private, and the
# topology by this point holds the copied path rather than the pool origin.
LICENSE_SELECTION_CONTEXT = "engulf_clab.license_pool.selection"
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
_VARIABLE_REFERENCE = re.compile(
    r"^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})$"
)
_LEGACY_STATE_DIRECTORY = ".engulf-clab"
# Allocation identity rides on the node environment rather than a top-level
# `uuid:` field. Containerlab's own schema has no `uuid` node property, so a
# topology carrying one is rejected by every subcommand that validates the raw
# document (graph, inspect, destroy) even though deploy accepted it. `env` is a
# field Containerlab already defines, so identity survives schema validation
# everywhere. The name is deliberately not edition-prefixed: it is the same
# variable the guest uses for its own UUID, so the license and the VM it is
# bound to cannot disagree.
UUID_ENVIRONMENT = "FOS_UUID"

# Fixed across every edition, matching engulf-clab-wan's LABEL_PREFIX
# convention: topology labels/env vars must stay portable regardless of the
# active application's product metadata. Unlike labels, the topology-local
# state directory below is deliberately still derived from application
# metadata, so every edition's state converges on the same directory as long
# as they share the same short_product_name.
LABEL_PREFIX = "ECLAB"
LICENSE_POOL_STRATEGY_ENVIRONMENT = f"{LABEL_PREFIX}_LICENSE_POOL_STRATEGY"
AUTO_LICENSE = f"{LABEL_PREFIX}_AUTO_LICENSE"
DISABLE_AUTO_LICENSE_ENVIRONMENT = f"{LABEL_PREFIX}_DISABLE_AUTO_LICENSE"
DEFAULT_LICENSE_KIND = "fortinet_fortigate"
INIT_LICENSE_POOL_COMMAND = "init-license-pool"
INSPECT_LICENSE_POOL_COMMAND = "inspect-license-pool"


_STRATEGY_VALUES = (
    ExplainedValue(
        LicenseStrategy.STICKY.value,
        "Retain active claims and preserve the existing claim-history preference.",
    ),
    ExplainedValue(
        LicenseStrategy.ROUND_ROBIN.value,
        "Choose the next available entry by index from the sorted pool.",
    ),
    ExplainedValue(
        LicenseStrategy.LEAST_RECENTLY_USED.value,
        "Choose the available entry with the oldest recorded use.",
    ),
)


@dataclass(frozen=True, slots=True)
class InitLicensePoolResult:
    """The collector's result, published for edition-specific registration rules."""

    exit_code: int
    pool: Path | None = None
    kind: str | None = None
    registration_changed: bool = False
    metadata_changed: bool = False


PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.license_pool", package="engulf_clab_license_pool")
    .add_command(
        INIT_LICENSE_POOL_COMMAND,
        "Register an ordered product-specific license pool for automatic allocation.",
    )
    .add_cli_argument(
        INIT_LICENSE_POOL_COMMAND,
        "PATH",
        "Select the license-pool directory to register.",
        values=ValueType.DIRECTORY_PATH,
        required=False,
        default=".",
    )
    .add_command(
        INSPECT_LICENSE_POOL_COMMAND,
        "Inspect a license pool's metadata, capacity, and active allocations.",
    )
    .add_cli_argument(
        INSPECT_LICENSE_POOL_COMMAND,
        "PATH",
        "Select the license-pool directory to inspect.",
        values=ValueType.DIRECTORY_PATH,
        required=False,
        default=".",
    )
    .add_cli_flag(
        "--alloc-details",
        "Show each allocated license filename and its owning lab directory.",
        command=INSPECT_LICENSE_POOL_COMMAND,
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--kind",
        "Associate the pool with this Containerlab node kind (legacy spelling).",
        command=INIT_LICENSE_POOL_COMMAND,
        values=ValueType.STRING,
        default=DEFAULT_LICENSE_KIND,
    )
    .add_cli_flag(
        "--eclab-kind",
        "Select the pool's Containerlab node kind; interactive init asks when omitted.",
        command=INIT_LICENSE_POOL_COMMAND,
        values=ValueType.STRING,
        default=DEFAULT_LICENSE_KIND,
    )
    .add_cli_flag(
        "--eclab-update",
        "Ask installed metadata contributors to update pool metadata they own.",
        command=INIT_LICENSE_POOL_COMMAND,
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--eclab-licence-pool-var",
        "Set a declared pool metadata variable as name=value; repeat to set several.",
        command=INIT_LICENSE_POOL_COMMAND,
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_node_prop(
        "license",
        "Select a license source, or request automatic allocation from a registered pool.",
        values=ValueType.STRING,
    )
    .add_node_var(
        UUID_ENVIRONMENT,
        "Set a stable node identity for repeatable license allocation.",
        values=ValueType.UUID,
    )
    .add_node_var(
        "ECLAB_LIC_CLAMP",
        "Require a specific available license filename or path from the selected pool.",
        values=ValueType.FILE_PATH,
    )
    .add_node_var(
        DISABLE_AUTO_LICENSE_ENVIRONMENT,
        "Disable fallback to registered pools for an unresolved license variable.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_runtime_var(
        LICENSE_POOL_STRATEGY_ENVIRONMENT,
        "Set the persistent license-pool selection strategy; the matching CLI flag takes precedence.",
        values=_STRATEGY_VALUES,
        default=LicenseStrategy.LEAST_RECENTLY_USED.value,
    )
    .add_cli_flag(
        "--eclab-license-pool-strategy",
        "Select the license-pool allocation strategy for this invocation.",
        values=_STRATEGY_VALUES,
        default=LicenseStrategy.LEAST_RECENTLY_USED.value,
        environment=LICENSE_POOL_STRATEGY_ENVIRONMENT,
    )
    .add_runtime_var(
        "ECLAB_LICENSE",
        "Set the default frozen-lab license source; the matching CLI flag takes precedence.",
        values=(ValueType.FILE_PATH, ValueType.DIRECTORY_PATH, ValueType.STRING),
    )
    .add_cli_flag(
        "--eclab-license",
        "Provide the default non-interactive frozen-lab license source.",
        values=(ValueType.FILE_PATH, ValueType.DIRECTORY_PATH, ValueType.STRING),
        environment="ECLAB_LICENSE",
    )
    .add_runtime_var(
        AUTO_LICENSE,
        "Request registered-pool allocation for every unresolved frozen license prompt.",
        values=ValueType.BOOLEAN,
        default=False,
    )
    .add_cli_flag(
        "--eclab-auto-license",
        "Resolve unresolved frozen license prompts from registered pools automatically.",
        environment=AUTO_LICENSE,
    )
    .add_runtime_var(
        "ECLAB_LICENSE_*",
        "Provide a node-specific frozen-lab license source.",
        values=(ValueType.FILE_PATH, ValueType.DIRECTORY_PATH, ValueType.STRING),
    )
    .annotate(
        INIT_LICENSE_POOL_COMMAND,
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=(
            "the canonical pool path and node kind are stored in ordered user state",
            "normal Containerlab execution is preempted",
        ),
        examples=(
            "eclab init-license-pool ./licenses --eclab-kind fortinet_fortigate",
        ),
    )
    .annotate(
        "PATH",
        commands=(INIT_LICENSE_POOL_COMMAND, INSPECT_LICENSE_POOL_COMMAND),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        INSPECT_LICENSE_POOL_COMMAND,
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=(
            "reports pool metadata and current license allocations without modifying them",
        ),
        examples=(
            "eclab inspect-license-pool ./licenses --alloc-details",
        ),
    )
    .annotate(
        "--alloc-details",
        commands=(INSPECT_LICENSE_POOL_COMMAND,),
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=("each active license claim is paired with its owning lab directory",),
    )
    .annotate(
        "--kind",
        commands=(INIT_LICENSE_POOL_COMMAND,),
        implies=("automatic allocation validates the effective node kind",),
    )
    .annotate(
        "--eclab-kind",
        commands=(INIT_LICENSE_POOL_COMMAND,),
        implies=("automatic allocation validates the effective node kind",),
    )
    .annotate(
        "--eclab-update",
        commands=(INIT_LICENSE_POOL_COMMAND,),
        implies=("each metadata contributor may prompt for fields it owns",),
    )
    .annotate(
        "license",
        commands=("deploy", "destroy"),
        lifecycle=(LifecycleStage.PREPARE_CALL, LifecycleStage.AFTER_CALL),
        requires=(
            "$POOL names an invocation environment variable containing a pool directory",
            "any other value naming a directory is itself the pool",
        ),
        implies=(
            "a successful deploy copies the selected license into lab-local state",
            "an unsuccessful deploy rolls back claims and copies created by that invocation",
        ),
        examples=(
            "$ROUTER_LICENSE_POOL",
            "/srv/licenses/router",
            AUTO_LICENSE,
            "__ECLAB_LICENSE_PROMPT__",
        ),
    )
    .annotate(
        UUID_ENVIRONMENT,
        commands=("deploy", "redeploy"),
        implies=("stable allocation identity across node renames",),
    )
    .annotate(
        "ECLAB_LIC_CLAMP",
        commands=("deploy", "redeploy"),
        requires=("license selects a $POOL",),
        path_base=PathBase.LICENSE_POOL,
    )
    .annotate(
        DISABLE_AUTO_LICENSE_ENVIRONMENT,
        commands=("deploy", "redeploy"),
        requires=("license names an undefined $VARIABLE",),
    )
    .annotate(
        "--eclab-license-pool-strategy",
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("active claims remain stable for deployment retries",),
    )
    .annotate(
        LICENSE_POOL_STRATEGY_ENVIRONMENT,
        commands=("deploy", "redeploy"),
        lifecycle=(LifecycleStage.PREPARE_CALL,),
        implies=("used when --eclab-license-pool-strategy is absent",),
    )
    .annotate(
        "ECLAB_LICENSE",
        commands=("deploy", "redeploy"),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--eclab-license",
        commands=("deploy", "redeploy"),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        AUTO_LICENSE,
        commands=("deploy", "redeploy"),
        implies=(
            "unresolved frozen license prompts request registered-pool allocation",
        ),
    )
    .annotate(
        "--eclab-auto-license",
        commands=("deploy", "redeploy"),
        conflicts_with=("--eclab-license",),
        implies=(
            "unresolved frozen license prompts request registered-pool allocation",
        ),
    )
    .annotate(
        "ECLAB_LICENSE_*",
        commands=("deploy", "redeploy"),
        requires=("license is __ECLAB_LICENSE_PROMPT__",),
        implies=("override ECLAB_LICENSE for the named node",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .use_case(
        "Lease one license file per node from a shared directory without embedding license contents."
    )
    .reject("Do not commit license files, pool paths, or generated lab-local copies.")
    .order(
        LifecycleStage.PREPARE_CALL,
        "License allocation mutates the parsed topology before final serialization.",
        after=("engulf_clab.lab_parser",),
        before=("engulf_clab.lab_writer",),
    )
    .route(
        "assign-node-license",
        "USAGE.md",
        "Read pool selection, stable identity, prompts, leases, and cleanup.",
    )
    .refer("USAGE.md")
)


@dataclass(frozen=True, slots=True)
class LicenseContract:
    state_prefix: str

    @property
    def clamp_environment(self) -> str:
        return f"{LABEL_PREFIX}_LIC_CLAMP"

    @property
    def prompt_marker(self) -> str:
        return f"__{LABEL_PREFIX}_LICENSE_PROMPT__"

    @property
    def license_environment(self) -> str:
        return f"{LABEL_PREFIX}_LICENSE"

    @property
    def state_directory(self) -> str:
        return f".{self.state_prefix.lower()}"

    def node_license_environment(self, node_name: str) -> str:
        node = "".join(
            character if character.isalnum() else "_" for character in node_name.upper()
        )
        return f"{self.license_environment}_{node}"


@dataclass(frozen=True, slots=True)
class _InvocationAllocation:
    claims: tuple[tuple[str, str, str], ...] = ()
    copies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RegisteredPool:
    path: str
    kind: str


@dataclass(frozen=True, slots=True)
class _AutomaticRequest:
    node: str
    pools: tuple[str, ...]
    clamp: str | None
    claim: str


@dataclass(frozen=True, slots=True)
class LicenseSelection:
    """One node's resolved license, as published on LICENSE_SELECTION_CONTEXT.

    `pool` is the directory a pooled license was allocated from, and is None
    when the license was named directly. Reading plugins should branch on
    `from_pool` rather than on the path, which is absolute and host-specific.
    """

    node: str
    source_name: str
    source_path: str
    pool: str | None = None

    @property
    def from_pool(self) -> bool:
        return self.pool is not None


def _log_selection(api: InvocationAPI, selection: object) -> None:
    if not isinstance(selection, Mapping):
        return
    for node, value in sorted(selection.items()):
        if isinstance(value, LicenseSelection):
            # Basename and a flag only: as with the selection log in
            # prepare_call, pool and source paths stay out of the record.
            api.logger.debug(
                "license provenance node=%r basename=%r from_pool=%r",
                node,
                value.source_name,
                value.from_pool,
            )


def license_contract(application: ApplicationMetadata) -> LicenseContract:
    short_name = getattr(application, "short_product_name", None)
    product = getattr(application, "product", None)
    name = short_name if isinstance(short_name, str) and short_name.strip() else product
    if not isinstance(name, str) or not name.strip():
        raise LicensePoolError("application product metadata must be a nonempty string")
    prefix = _NON_ALPHANUMERIC.sub("_", name.upper()).strip("_")
    if not prefix:
        raise LicensePoolError(f"cannot derive environment prefix from {name!r}")
    return LicenseContract(prefix)


class LicensePoolPlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.license_pool"
    schema = PLUGIN_SCHEMA
    # Edition adapters consume INIT_LICENSE_POOL_CONTEXT from before_goal;
    # run the shared collector before those adapters (currently priority 70).
    priority = 75
    context_reads = (
        frozenset(
            {
                TOPOLOGY_CONTEXT,
                _INVOCATION_ALLOCATION_CONTEXT,
                _INIT_LICENSE_POOL_EXIT_CONTEXT,
                _INSPECT_LICENSE_POOL_EXIT_CONTEXT,
                INIT_LICENSE_POOL_CONTEXT,
                LICENSE_SELECTION_CONTEXT,
                LICENSE_ALLOCATION_HANDOFF_CONTEXT,
            }
        )
        | SCHEMA_CONTEXTS
    )
    context_writes = (
        frozenset(
            {
                _INVOCATION_ALLOCATION_CONTEXT,
                _INIT_LICENSE_POOL_EXIT_CONTEXT,
                _INSPECT_LICENSE_POOL_EXIT_CONTEXT,
                INIT_LICENSE_POOL_CONTEXT,
                LICENSE_SELECTION_CONTEXT,
                LICENSE_POOL_AVAILABILITY_CONTEXT,
            }
        )
        | SCHEMA_CONTEXTS
    )

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if invocation.arguments[:1] == ("defrost",):
            try:
                with api.lease("license-pool-registry"):
                    registered = bool(
                        LicensePoolManager(api.state(StateScope.USER)).registered_pools()
                    )
            except (LicensePoolError, OSError, ValueError) as error:
                api.logger.warning(
                    "could not check registered license pools: %s", error
                )
                availability = LicensePoolAvailability(None)
            else:
                availability = LicensePoolAvailability(registered)
            publish_license_pool_availability(api, availability)
        if invocation.arguments[:1] == (INSPECT_LICENSE_POOL_COMMAND,):
            application_name = api.application.short_product_name or api.application.product
            try:
                options = _parse_inspect_license_pool_options(
                    invocation.arguments[1:], invocation.cwd
                )
                pool_lease = _lease(str(options.pool))
                with api.leases(
                    tuple(sorted(("license-pool-registry", pool_lease)))
                ):
                    report = _inspect_pool_report(
                        api.state(StateScope.USER),
                        options.pool,
                        alloc_details=options.alloc_details,
                    )
            except (
                LicensePoolError,
                LicensePoolMetadataError,
                OSError,
                ValueError,
            ) as error:
                api.logger.error(
                    "%s %s: %s", application_name, INSPECT_LICENSE_POOL_COMMAND, error
                )
                exit_code = 2
            else:
                api.logger.info("%s", "\n".join(report))
                exit_code = 0
            api.set_context(
                _INSPECT_LICENSE_POOL_EXIT_CONTEXT,
                exit_code,
                allow_unused=True,
            )
            return None
        if (
            not invocation.arguments
            or invocation.arguments[0] != INIT_LICENSE_POOL_COMMAND
        ):
            return None
        application_name = api.application.short_product_name or api.application.product
        pool: Path | None = None
        kind: str | None = None
        registration_changed = False
        metadata_changed = False
        interactive = sys.stdin.isatty()
        try:
            options = _parse_init_license_pool_options(
                invocation.arguments[1:], invocation.cwd
            )
            if not options.kind_explicit and interactive:
                options = _InitLicensePoolOptions(
                    pool=options.pool,
                    kind=_prompt_license_pool_kind(),
                    kind_explicit=options.kind_explicit,
                    update=options.update,
                    variable_overrides=options.variable_overrides,
                )
            pool, kind = options.pool, options.kind
            initial_metadata = load_pool_metadata(pool)
            contributions = _collect_pool_metadata(
                pool=pool,
                kind=kind,
                arguments=invocation.arguments[1:],
                environment=invocation.environment,
                cwd=invocation.cwd,
                metadata=initial_metadata,
                kind_explicit=options.kind_explicit,
                update=options.update,
                interactive=interactive,
                variable_overrides=options.variable_overrides,
            )
            with api.leases(("license-pool-registry",)):
                current_metadata = load_pool_metadata(pool)
                if contributions:
                    merged_metadata = current_metadata.merged(contributions)
                    metadata_changed = (
                        merged_metadata.to_document() != current_metadata.to_document()
                    )
                    if metadata_changed:
                        _write_pool_metadata(pool, merged_metadata)
                manager = LicensePoolManager(api.state(StateScope.USER))
                managed = run_pool_managers(
                    (manager,),
                    manager,
                    PoolManagerRequest(path=pool, kind=kind),
                )
                registration_changed = managed.changed
        except (
            LicensePoolError,
            LicensePoolMetadataError,
            OSError,
            ValueError,
        ) as error:
            api.logger.error(
                "%s %s: %s", application_name, INIT_LICENSE_POOL_COMMAND, error
            )
            exit_code = 2
            result = InitLicensePoolResult(
                exit_code=exit_code,
                pool=pool,
                kind=kind,
                registration_changed=registration_changed,
                metadata_changed=metadata_changed,
            )
        else:
            api.logger.info(
                "%s license pool for node kind=%r",
                "registered" if registration_changed else "updated",
                kind,
            )
            exit_code = 0
            result = InitLicensePoolResult(
                exit_code=exit_code,
                pool=pool,
                kind=kind,
                registration_changed=registration_changed,
                metadata_changed=metadata_changed,
            )
        api.set_context(
            _INIT_LICENSE_POOL_EXIT_CONTEXT,
            exit_code,
            allow_unused=True,
        )
        api.set_context(INIT_LICENSE_POOL_CONTEXT, result, allow_unused=True)
        return None

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering license-pool help")
        contract = license_contract(api.application)
        return (
            f"  {INIT_LICENSE_POOL_COMMAND} [PATH] [--kind KIND] [--eclab-kind KIND] [--eclab-update] [--eclab-licence-pool-var NAME=VALUE]  Register an automatic license pool\n"
            "      Interactive init asks for the product kind and installed contributors' missing metadata.\n"
            "      Existing metadata is reused; --eclab-update asks contributors to refresh it.\n"
            "      Set typed metadata with --eclab-licence-pool-var NAME=VALUE; repeat as needed.\n"
            "      Lists use ';' separators and ';;' for a literal semicolon.\n"
            f"  {INSPECT_LICENSE_POOL_COMMAND} [PATH] [--alloc-details]\n"
            "      Show pool metadata and used/total; allocation details name each lab.\n"
            "      PATH defaults to the current directory.\n"
            "  Node YAML fields:\n"
            "    license: $POOL              Allocate from invocation environment POOL directory\n"
            "    license: <directory>        Allocate from that pool directory directly\n"
            f"    license: {AUTO_LICENSE}  Allocate from the first registered pool for the node kind\n"
            f"    env.{UUID_ENVIRONMENT}: <uuid>     Recommended stable allocation identity\n"
            f"    env.{contract.clamp_environment}: file   Require this available pool filename/path\n"
            f"    env.{DISABLE_AUTO_LICENSE_ENVIRONMENT}: true  Disable unresolved-variable fallback\n"
            f"    license: {contract.prompt_marker}  Prompt for a file, pool, or $VARIABLE in frozen labs\n"
            "  --eclab-license-pool-strategy STRATEGY\n"
            "      least-recently-used (default), sticky, or round-robin\n"
            f"  {LICENSE_POOL_STRATEGY_ENVIRONMENT} is the persistent strategy default; CLI wins.\n"
            "  --eclab-license VALUE        Default non-interactive frozen-lab license\n"
            f"  {contract.license_environment} is the persistent environment default; "
            "--eclab-license wins.\n"
            "  --eclab-auto-license  Allocate every unresolved frozen prompt from registered pools\n"
            f"  {contract.license_environment}_<NODE> remains the per-node prompt override.\n"
            "  Registered pools are matched to the effective node kind in registration order.\n"
            "  Pools contain top-level regular files and are leased across workspaces.\n"
            "  Deploy and redeploy log each selected license basename, pool, and node.\n"
            "  Failed deployment rolls back new claims; successful destroy releases workspace claims."
        )

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        if not event.wrapper_args:
            return None
        command = event.wrapper_args[0]
        if command == INIT_LICENSE_POOL_COMMAND:
            context_key = _INIT_LICENSE_POOL_EXIT_CONTEXT
        elif command == INSPECT_LICENSE_POOL_COMMAND:
            context_key = _INSPECT_LICENSE_POOL_EXIT_CONTEXT
        else:
            return None
        exit_code = api.require_context(context_key)
        if type(exit_code) is not int:
            raise LicensePoolError(f"invalid {command} invocation context")
        return CallContribution(preempt_exit_code=exit_code)

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        handoff = api.get_context(LICENSE_ALLOCATION_HANDOFF_CONTEXT)
        if isinstance(handoff, LicenseAllocationHandoff):
            return
        session = api.require_context(TOPOLOGY_CONTEXT)
        if not isinstance(session, TopologySession):
            raise LicensePoolError("invalid shared topology session")
        topology = session.original_document()
        _warn_legacy_uuid(api, topology)
        workspace = api.state(StateScope.WORKSPACE).root
        contract = license_contract(api.application)
        strategy = _license_strategy(event.environment)
        state = api.state(StateScope.USER)
        registered = _registered_pools(state)
        requests = _requests(
            topology,
            event.environment,
            workspace,
            contract,
            registered=registered,
        )
        prompt_requests, direct, automatic_prompts = _prompt_requests(
            topology,
            event.environment,
            workspace,
            contract,
            auto_prompts=_auto_license_requested(event.environment),
        )
        automatic = _automatic_requests(
            topology,
            event.environment,
            workspace,
            contract,
            registered,
            automatic_prompts=automatic_prompts,
        )
        requests.extend(prompt_requests)
        if not requests and not automatic and not direct:
            return
        with api.leases(
            tuple(
                sorted(
                    {_lease(pool) for _node, pool, _clamp, _claim in requests}
                    | {_lease(pool) for request in automatic for pool in request.pools}
                )
            )
        ):
            assigned, created_claims = _claim_all_with_created(
                state, requests, automatic, strategy
            )
        allocation = _InvocationAllocation(claims=created_claims)
        try:
            api.set_context(_INVOCATION_ALLOCATION_CONTEXT, allocation)
            assigned.update({claim: source for claim, source in direct.values()})
            mutation = editor(api, self.plugin_id)
            selections = [(node, claim) for node, _pool, _clamp, claim in requests]
            selections.extend((request.node, request.claim) for request in automatic)
            selections.extend(
                (node, claim) for node, (claim, _source) in direct.items()
            )
            # Only `requests` carry a pool; `direct` entries name a file. Prompt
            # answers that resolved to a pool were folded into `requests` above,
            # so they are correctly reported as pooled.
            pools = {node: pool for node, pool, _clamp, _claim in requests}
            pools.update(
                {
                    request.node: str(Path(assigned[request.claim]).parent)
                    for request in automatic
                }
            )
            published: dict[str, LicenseSelection] = {}
            for node, claim in selections:
                source = Path(assigned[claim])
                published[node] = LicenseSelection(
                    node=node,
                    source_name=source.name,
                    source_path=str(source),
                    pool=pools.get(node),
                )
                target = _copy_path(session.path.parent, claim, source.name, contract)
                if not target.exists():
                    allocation = _InvocationAllocation(
                        claims=allocation.claims,
                        copies=(*allocation.copies, str(target)),
                    )
                    api.set_context(_INVOCATION_ALLOCATION_CONTEXT, allocation)
                copied = _copy_to_lab(source, session.path.parent, claim, contract)
                api.logger.info(
                    "selected license basename=%r from pool=%r for node=%r",
                    source.name,
                    published[node].pool,
                    node,
                )
                mutation.modify(("topology", "nodes", node, "license"), str(copied))
            api.set_context(LICENSE_SELECTION_CONTEXT, MappingProxyType(published))
            # Read back at the point of publication, and log provenance from
            # what the context actually holds. Reading marks the context
            # consumed, so an edition that ships no reader for this extension
            # point does not trip the framework's unread-context warning.
            _log_selection(api, api.get_context(LICENSE_SELECTION_CONTEXT))
        except BaseException:
            # Engulf never sends prepare_failed to the plugin that raised, so this
            # attempt's claims and copies are released here. BaseException rather
            # than Exception: an interrupt is not an Exception and would otherwise
            # strand a claimed license on Ctrl-C.
            self._rollback_deploy(api, allocation)
            raise

    def prepare_failed(self, event: PreparationFailedEvent, api: InvocationAPI) -> None:
        if not is_topology_mutation_command(event.wrapper_args):
            return
        if isinstance(
            api.get_context(LICENSE_ALLOCATION_HANDOFF_CONTEXT),
            LicenseAllocationHandoff,
        ):
            return
        allocation = api.get_context(_INVOCATION_ALLOCATION_CONTEXT)
        if isinstance(allocation, _InvocationAllocation):
            self._rollback_deploy(api, allocation)

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if isinstance(
            api.get_context(LICENSE_ALLOCATION_HANDOFF_CONTEXT),
            LicenseAllocationHandoff,
        ):
            return
        allocation = api.get_context(_INVOCATION_ALLOCATION_CONTEXT)
        if is_topology_mutation_command(event.wrapper_args):
            if isinstance(allocation, _InvocationAllocation) and (
                event.outcome.kind is not OutcomeKind.COMPLETED
                or event.outcome.exit_code != 0
            ):
                self._rollback_deploy(api, allocation)
            return
        if (
            not event.wrapper_args
            or event.wrapper_args[0] != "destroy"
            or event.mode is CallMode.HELP
        ):
            return
        if event.outcome.kind is not OutcomeKind.COMPLETED or event.outcome.exit_code:
            return
        with api.lease("license-pool-registry"):
            state = api.state(StateScope.USER)
            contract = license_contract(api.application)
            if any(value in {"-a", "--all"} for value in event.wrapper_args[1:]):
                # Read the claimed workspaces before releasing them: afterwards the
                # registry no longer records which labs hold copied licenses, and
                # releasing the registry alone would leave every copy on disk.
                roots = _claimed_workspaces(state)
                _release_all(state)
                for root in roots:
                    _remove_license_copies(Path(root), contract)
                return
            workspace = api.state(StateScope.WORKSPACE)
            _release_workspace(state, str(workspace.root))
            _remove_license_copies(workspace.root, contract)

    def _rollback_deploy(
        self, api: InvocationAPI, allocation: _InvocationAllocation
    ) -> None:
        pools = tuple(sorted({pool for pool, _path, _claim in allocation.claims}))
        with api.leases(tuple(_lease(pool) for pool in pools)):
            _release_claims(api.state(StateScope.USER), allocation.claims)
        for value in allocation.copies:
            target = Path(value)
            target.unlink(missing_ok=True)
            _remove_empty_copy_parents(target.parent)


def _pool(
    value: str, environ: Mapping[str, str], contract: LicenseContract
) -> Path | None:
    """Resolve one node `license:` value to a pool directory, or None.

    The lab parser expands Containerlab environment expressions before any
    plugin reads the topology, so `license: $POOL` normally arrives here
    already rendered as the pool directory itself. A pool is therefore
    recognised by the value naming a directory, not by a leading `$`. A bare
    An exact `$NAME` still survives expansion when the variable is unset; the
    caller reserves that case for registered-pool fallback before invoking this
    resolver. Anything else -- a regular file, the frozen prompt marker, or a
    path that does not exist -- is not this plugin's to allocate and is left for
    Containerlab or `_prompt_requests` to handle.
    """
    # An empty YAML string is not a path selector.  Path("") resolves to the
    # current directory, which would otherwise make an omitted-looking value
    # claim licenses from the process working directory.
    if not value or value == contract.prompt_marker:
        return None
    variable = _VARIABLE_REFERENCE.fullmatch(value)
    if variable is not None:
        pool_name = variable.group(1) or variable.group(2)
        if not pool_name or pool_name not in environ:
            raise LicensePoolError(f"license pool ${pool_name} is not set")
        pool_value = environ[pool_name]
        if not pool_value:
            raise LicensePoolError(f"license pool ${pool_name} is empty")
        pool = Path(pool_value).expanduser().resolve()
        if not pool.is_dir():
            raise LicensePoolError(
                f"license pool ${pool_name} is not a directory: {pool}"
            )
        return pool
    candidate = Path(value).expanduser().resolve()
    return candidate if candidate.is_dir() else None


def _requests(
    data: dict[str, Any],
    environ: Mapping[str, str],
    workspace: Path,
    contract: LicenseContract,
    *,
    registered: tuple[_RegisteredPool, ...] = (),
) -> list[tuple[str, str, str | None, str]]:
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        raise LicensePoolError("topology.nodes is required")
    try:
        resolved_nodes = effective_nodes(data)
    except TopologyError as error:
        raise LicensePoolError(str(error)) from error
    result = []
    for node in resolved_nodes:
        license_value = node.data.get("license")
        if not isinstance(license_value, str):
            continue
        if (
            license_value == AUTO_LICENSE
            or _undefined_variable(license_value, environ) is not None
        ):
            continue
        pool = _pool(license_value, environ, contract)
        if pool is None:
            continue
        env = node.data.get("env", {})
        if env is None:
            env = {}
        if not isinstance(env, Mapping):
            raise LicensePoolError(f"node {node.name} env must be a YAML mapping")
        clamp = env.get(contract.clamp_environment)
        if clamp is not None and not isinstance(clamp, str):
            raise LicensePoolError(
                f"node {node.name} {contract.clamp_environment} must be a string"
            )
        identity = env.get(UUID_ENVIRONMENT, node.name)
        if not isinstance(identity, str) or not identity:
            raise LicensePoolError(
                f"node {node.name} {UUID_ENVIRONMENT} must be a nonempty string"
            )
        registration = next(
            (item for item in registered if item.path == str(pool)), None
        )
        if registration is not None:
            kind = node.data.get("kind")
            if kind != registration.kind:
                raise LicensePoolError(
                    f"node {node.name} kind {kind!r} does not match registered "
                    f"license pool kind {registration.kind!r}"
                )
        result.append((node.name, str(pool), clamp, f"{workspace}:{identity}"))
    return result


def _automatic_requests(
    data: dict[str, Any],
    environ: Mapping[str, object],
    workspace: Path,
    contract: LicenseContract,
    registered: tuple[_RegisteredPool, ...],
    *,
    automatic_prompts: tuple[str, ...] = (),
) -> list[_AutomaticRequest]:
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        raise LicensePoolError("topology.nodes is required")
    try:
        resolved_nodes = effective_nodes(data)
    except TopologyError as error:
        raise LicensePoolError(str(error)) from error
    result: list[_AutomaticRequest] = []
    for node in resolved_nodes:
        license_value = node.data.get("license")
        if not isinstance(license_value, str):
            continue
        node_env = node.data.get("env", {})
        if node_env is None:
            node_env = {}
        if not isinstance(node_env, Mapping):
            raise LicensePoolError(f"node {node.name} env must be a YAML mapping")
        explicit = license_value == AUTO_LICENSE
        prompted = node.name in automatic_prompts
        implicit = _undefined_variable(license_value, environ) is not None
        if (
            not explicit
            and not prompted
            and (not implicit or _auto_license_disabled(node_env))
        ):
            continue
        kind = node.data.get("kind")
        if not isinstance(kind, str) or not kind:
            raise LicensePoolError(
                f"node {node.name} requires a kind for automatic license allocation"
            )
        pools = tuple(item.path for item in registered if item.kind == kind)
        if not pools:
            raise LicensePoolError(
                f"no registered license pool found for node {node.name} kind {kind!r}"
            )
        clamp = node_env.get(contract.clamp_environment)
        if clamp is not None and not isinstance(clamp, str):
            raise LicensePoolError(
                f"node {node.name} {contract.clamp_environment} must be a string"
            )
        identity = node_env.get(UUID_ENVIRONMENT, node.name)
        if not isinstance(identity, str) or not identity:
            raise LicensePoolError(
                f"node {node.name} {UUID_ENVIRONMENT} must be a nonempty string"
            )
        result.append(
            _AutomaticRequest(
                node.name,
                pools,
                clamp,
                f"{workspace}:{identity}",
            )
        )
    return result


def _undefined_variable(value: str, environ: Mapping[str, object]) -> str | None:
    match = _VARIABLE_REFERENCE.fullmatch(value)
    if match is None:
        return None
    variable = match.group(1) or match.group(2)
    if variable in environ:
        return None
    return variable


def _auto_license_disabled(environment: Mapping[str, object]) -> bool:
    value = environment.get(DISABLE_AUTO_LICENSE_ENVIRONMENT)
    return value is True or (
        isinstance(value, str) and value.strip().casefold() == "true"
    )


def _auto_license_requested(environment: Mapping[str, object]) -> bool:
    value = environment.get(AUTO_LICENSE)
    return value is True or (
        isinstance(value, str)
        and value.strip().casefold() in {"1", "true", "yes", "on"}
    )


def _prompt_requests(
    data: dict[str, Any],
    environ: Mapping[str, object],
    workspace: Path,
    contract: LicenseContract,
    *,
    auto_prompts: bool = False,
) -> tuple[
    list[tuple[str, str, str | None, str]],
    dict[str, tuple[str, str]],
    tuple[str, ...],
]:
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        raise LicensePoolError("topology.nodes is required")
    try:
        resolved_nodes = effective_nodes(data)
    except TopologyError as error:
        raise LicensePoolError(str(error)) from error
    pools: list[tuple[str, str, str | None, str]] = []
    direct: dict[str, tuple[str, str]] = {}
    automatic: list[str] = []
    for node in resolved_nodes:
        if node.data.get("license") != contract.prompt_marker:
            continue
        node_name = node.name
        node_env = node.data.get("env", {})
        if node_env is None:
            node_env = {}
        if not isinstance(node_env, Mapping):
            raise LicensePoolError(f"node {node_name} env must be a YAML mapping")
        identity = node_env.get(UUID_ENVIRONMENT, node_name)
        if not isinstance(identity, str) or not identity:
            raise LicensePoolError(
                f"node {node_name} {UUID_ENVIRONMENT} must be a nonempty string"
            )
        if auto_prompts:
            automatic.append(node_name)
            continue
        claim = f"{workspace}:{identity}"
        key = contract.node_license_environment(node_name)
        value = environ.get(key) or environ.get(contract.license_environment)
        if not value and sys.stdin.isatty():
            value = input(
                f"License for {node_name} (auto, file, pool directory, or $VARIABLE): "
            ).strip()
        if not isinstance(value, str) or not value:
            raise LicensePoolError(
                f"frozen license for {node_name} requires {key}, {contract.license_environment}, or an interactive terminal"
            )
        if value.startswith("$"):
            variable = value[1:].strip("{}")
            variable_value = environ.get(variable, "")
            value = variable_value if isinstance(variable_value, str) else ""
            if not value:
                raise LicensePoolError(
                    f"license variable {variable} is not set for node {node_name}"
                )
        if isinstance(value, str) and (
            value.casefold() == "auto" or value == AUTO_LICENSE
        ):
            automatic.append(node_name)
            continue
        if not isinstance(value, str):
            raise LicensePoolError(
                f"invalid frozen license choice for node {node_name}"
            )
        candidate = Path(value).expanduser().resolve()
        if candidate.is_file():
            direct[node_name] = (claim, str(candidate))
        elif candidate.is_dir():
            pools.append((node_name, str(candidate), None, claim))
        else:
            raise LicensePoolError(
                f"frozen license choice for {node_name} is not a file or directory: {candidate}"
            )
    return pools, direct, tuple(automatic)


@dataclass(frozen=True, slots=True)
class _InitLicensePoolOptions:
    pool: Path
    kind: str
    kind_explicit: bool
    update: bool
    variable_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _InspectLicensePoolOptions:
    pool: Path
    alloc_details: bool


def _parse_init_license_pool_options(
    arguments: tuple[str, ...], cwd: Path
) -> _InitLicensePoolOptions:
    path_value = "."
    kind = DEFAULT_LICENSE_KIND
    kind_explicit = False
    update = False
    variable_overrides: list[tuple[str, str]] = []
    positional = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"--kind", "--eclab-kind"}:
            index += 1
            if index >= len(arguments):
                raise LicensePoolError(f"{argument} requires a value")
            kind = arguments[index]
            kind_explicit = True
        elif argument.startswith(("--kind=", "--eclab-kind=")):
            kind = argument.partition("=")[2]
            kind_explicit = True
        elif argument == "--eclab-update":
            update = True
        elif argument == "--eclab-licence-pool-var":
            index += 1
            if index >= len(arguments):
                raise LicensePoolError(f"{argument} requires NAME=VALUE")
            variable_overrides.append(
                _parse_metadata_variable_argument(arguments[index])
            )
        elif argument.startswith("--eclab-licence-pool-var="):
            variable_overrides.append(
                _parse_metadata_variable_argument(argument.partition("=")[2])
            )
        elif not argument.startswith("-") and not positional:
            path_value = argument
            positional = True
        index += 1
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", kind) is None:
        raise LicensePoolError(
            "license pool kind must be a lowercase Containerlab kind token"
        )
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    pool = candidate.resolve()
    if not pool.is_dir():
        raise LicensePoolError("license pool path must be an existing directory")
    return _InitLicensePoolOptions(
        pool, kind, kind_explicit, update, tuple(variable_overrides)
    )


def _parse_metadata_variable_argument(value: str) -> tuple[str, str]:
    name, separator, variable_value = value.partition("=")
    if not separator or not name:
        raise LicensePoolError("--eclab-licence-pool-var requires NAME=VALUE")
    return name, variable_value


def _parse_init_license_pool(arguments: tuple[str, ...], cwd: Path) -> tuple[Path, str]:
    """Compatibility wrapper for callers that need only path and kind."""
    options = _parse_init_license_pool_options(arguments, cwd)
    return options.pool, options.kind


def _parse_inspect_license_pool_options(
    arguments: tuple[str, ...], cwd: Path
) -> _InspectLicensePoolOptions:
    path_value = "."
    alloc_details = False
    positional = False
    for argument in arguments:
        if argument == "--alloc-details":
            alloc_details = True
        elif argument.startswith("-"):
            raise LicensePoolError(
                f"inspect-license-pool does not support option {argument}"
            )
        elif positional:
            raise LicensePoolError("inspect-license-pool accepts at most one PATH")
        else:
            path_value = argument
            positional = True
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    pool = candidate.resolve()
    if not pool.is_dir():
        raise LicensePoolError(f"license-pool path is not an existing directory: {pool}")
    return _InspectLicensePoolOptions(pool, alloc_details)


def _inspect_pool_report(
    state: Any,
    pool: Path,
    *,
    alloc_details: bool,
) -> tuple[str, ...]:
    metadata = load_pool_metadata(pool)
    with state.transaction() as locked:
        registry = _load(locked)

    pool_path = str(pool)
    kind = next(
        (
            registration["kind"]
            for registration in registry["registrations"]
            if registration["path"] == pool_path
        ),
        None,
    )
    entry = registry["pools"].get(pool_path, {})
    allocations: dict[str, str] = entry.get("allocations", {})
    files = set(_pool_files(pool_path))
    used = files.intersection(allocations)

    lines = [
        f"POOL: {pool_path!r}",
        f"KIND: {kind if kind is not None else '(not registered)'}",
        "METADATA:",
    ]
    if metadata.exists:
        lines.extend(
            f"  {line}"
            for line in json.dumps(
                metadata.to_document(), indent=2, sort_keys=True
            ).splitlines()
        )
    else:
        lines.append("  (none)")
    lines.append(f"USAGE: {len(used)}/{len(files)}")
    if alloc_details:
        lines.append("ALLOCATIONS:")
        if allocations:
            for license_path, claim in sorted(allocations.items()):
                lab_path = claim.rsplit(":", 1)[0] if ":" in claim else "(unknown)"
                unavailable = (
                    " [missing or no longer eligible]"
                    if license_path not in files
                    else ""
                )
                lines.append(
                    f"  {Path(license_path).name!r}: {lab_path!r}{unavailable}"
                )
        else:
            lines.append("  (none)")
    return tuple(lines)


def _prompt_license_pool_kind() -> str:
    try:
        answer = input(
            "Product / Containerlab node kind (for example fortinet_fortigate) "
            f"[{DEFAULT_LICENSE_KIND}]: "
        ).strip()
    except EOFError as error:
        raise LicensePoolMetadataError(
            "init-license-pool cancelled before product selection"
        ) from error
    kind = answer or DEFAULT_LICENSE_KIND
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", kind) is None:
        raise LicensePoolMetadataError(
            "product kind must be a lowercase Containerlab kind token"
        )
    return kind


def _collect_pool_metadata(
    *,
    pool: Path,
    kind: str,
    arguments: tuple[str, ...],
    environment: Mapping[str, str],
    cwd: Path,
    metadata: PoolMetadata,
    kind_explicit: bool,
    update: bool,
    interactive: bool,
    variable_overrides: tuple[tuple[str, str], ...] = (),
) -> dict[str, Mapping[str, Any]]:
    contributions: dict[str, Mapping[str, Any]] = {}
    contributors = discover_metadata_contributors()
    declarations = {
        contributor.contributor_id: metadata_variables_for(contributor)
        for contributor in contributors
    }
    targets: dict[str, list[tuple[str, LicensePoolVariable]]] = {}
    for contributor_id, variables in declarations.items():
        for variable in variables:
            target = (contributor_id, variable)
            targets.setdefault(variable.name, []).append(target)
            targets.setdefault(f"{contributor_id}.{variable.name}", []).append(target)

    explicit_values: dict[tuple[str, str], Any] = {}
    for selector_name, raw_value in variable_overrides:
        matches = {
            (contributor_id, variable.name): (contributor_id, variable)
            for contributor_id, variable in targets.get(selector_name, ())
        }
        if not matches:
            raise LicensePoolMetadataError(
                f"unknown license-pool metadata variable {selector_name!r}"
            )
        if len(matches) > 1:
            qualified = ", ".join(
                sorted(
                    f"{contributor_id}.{variable.name}"
                    for contributor_id, variable in matches.values()
                )
            )
            raise LicensePoolMetadataError(
                f"license-pool variable {selector_name!r} is ambiguous; use one of: {qualified}"
            )
        target = next(iter(matches.values()))
        key = (target[0], target[1].name)
        if key in explicit_values:
            raise LicensePoolMetadataError(
                f"license-pool variable {selector_name!r} was supplied more than once"
            )
        explicit_values[key] = parse_license_pool_variable_value(target[1], raw_value)

    for contributor in contributors:
        contributor_id = contributor.contributor_id
        existing = metadata.for_contributor(contributor_id)
        own_variables = declarations[contributor_id]
        cli_values = {
            variable.name: explicit_values[(contributor_id, variable.name)]
            for variable in own_variables
            if (contributor_id, variable.name) in explicit_values
        }
        resolution_context = LicensePoolMetadataContext(
            pool=pool,
            kind=kind,
            kind_explicit=kind_explicit,
            arguments=arguments,
            environment=MappingProxyType(dict(environment)),
            cwd=cwd,
            existing=existing,
            legacy=MappingProxyType(dict(metadata.legacy)),
            metadata_file_exists=metadata.exists,
            update=update,
            interactive=interactive,
            variable_values=_readonly_variable_values(cli_values),
        )
        contributor_values = _resolve_contributor_variable_values(
            contributor, own_variables, resolution_context
        )
        variable_values: dict[str, Any] = {}
        for variable in own_variables:
            current = existing.get(variable.name, NO_DEFAULT)
            key = (contributor_id, variable.name)
            if current is not NO_DEFAULT:
                # Fail clearly when a declaration changes incompatibly with a
                # value already stored in the shared manifest.
                try:
                    current = parse_license_pool_variable_value(
                        variable,
                        format_license_pool_variable_value(variable, current),
                    )
                except LicensePoolMetadataError:
                    if key not in explicit_values and not update:
                        raise
                    current = NO_DEFAULT
            if key in explicit_values:
                value = explicit_values[key]
            elif variable.name in contributor_values:
                value = contributor_values[variable.name]
            elif current is not NO_DEFAULT and not update:
                value = current
            elif interactive:
                prompt_default = (
                    current
                    if update and current is not NO_DEFAULT
                    else variable.default
                )
                value = _prompt_license_pool_variable(
                    contributor_id, variable, prompt_default
                )
            elif variable.default is not NO_DEFAULT:
                value = variable.default
            elif variable.optional:
                continue
            else:
                qualified = f"{contributor_id}.{variable.name}"
                raise LicensePoolMetadataError(
                    f"license-pool variable {qualified!r} needs a value; "
                    "run init-license-pool interactively or supply "
                    f"--eclab-licence-pool-var {qualified}=<value>"
                )
            if value is NO_DEFAULT:
                continue
            variable_values[variable.name] = value

        context = LicensePoolMetadataContext(
            pool=pool,
            kind=kind,
            kind_explicit=kind_explicit,
            arguments=arguments,
            environment=MappingProxyType(dict(environment)),
            cwd=cwd,
            existing=existing,
            legacy=MappingProxyType(dict(metadata.legacy)),
            metadata_file_exists=metadata.exists,
            update=update,
            interactive=interactive,
            variable_values=_readonly_variable_values(variable_values),
        )
        contribution = validate_contribution(
            contributor_id,
            contributor.collect_metadata(context),
        )
        combined = dict(contribution or {})
        combined.update(variable_values)
        if combined:
            validated = validate_contribution(contributor_id, combined)
            if validated is not None:
                contributions[contributor_id] = validated
    return contributions


def _readonly_variable_values(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            name: tuple(value) if isinstance(value, list) else value
            for name, value in values.items()
        }
    )


def _resolve_contributor_variable_values(
    contributor: LicensePoolMetadataContributor,
    variables: tuple[LicensePoolVariable, ...],
    context: LicensePoolMetadataContext,
) -> Mapping[str, Any]:
    resolver = getattr(contributor, "resolve_variable_values", None)
    if resolver is None:
        return MappingProxyType({})
    if not callable(resolver):
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor.contributor_id!r} "
            "resolve_variable_values must be callable"
        )
    try:
        supplied = resolver(context)
    except LicensePoolMetadataError:
        raise
    except Exception as error:
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor.contributor_id!r} "
            "resolve_variable_values failed"
        ) from error
    if not isinstance(supplied, Mapping) or any(
        not isinstance(name, str) for name in supplied
    ):
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor.contributor_id!r} "
            "resolve_variable_values must return a string-keyed mapping"
        )
    declarations = {variable.name: variable for variable in variables}
    unknown = set(supplied) - set(declarations)
    if unknown:
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor.contributor_id!r} "
            f"resolved undeclared variables: {', '.join(sorted(unknown))}"
        )
    return MappingProxyType(
        {
            name: validate_license_pool_variable_value(declarations[name], value)
            for name, value in supplied.items()
        }
    )


def _prompt_license_pool_variable(
    contributor_id: str,
    variable: LicensePoolVariable,
    default: Any,
) -> Any:
    qualified = f"{contributor_id}.{variable.name}"
    description = f"{variable.description} [{qualified}]"
    choices = (
        f" Choices: {', '.join(variable.choices)}."
        if variable.type
        in {
            LicensePoolVariableType.CHOICE,
            LicensePoolVariableType.MULTI_CHOICE,
        }
        else ""
    )
    if variable.type is LicensePoolVariableType.STRING:
        description += " Enter text."
    elif variable.type is LicensePoolVariableType.STRING_LIST:
        description += " Enter strings separated by ';'; use ';;' for a literal ';'."
    elif variable.type is LicensePoolVariableType.CHOICE:
        description += " Choose one value."
    elif variable.type is LicensePoolVariableType.MULTI_CHOICE:
        description += (
            " Choose any values separated by ';'; use ';;' for a literal ';'."
        )
    elif variable.type is LicensePoolVariableType.BOOLEAN:
        description += " Enter true or false."
    elif variable.type is LicensePoolVariableType.INTEGER:
        description += " Enter a whole number."
    elif variable.type is LicensePoolVariableType.FLOAT:
        description += " Enter a finite number."
    default_text = (
        f" [{format_license_pool_variable_value(variable, default)}]"
        if default is not NO_DEFAULT
        else ""
    )
    optional_text = (
        " Leave blank to skip." if variable.optional and default is NO_DEFAULT else ""
    )
    prompt = f"{description}{choices}{optional_text}{default_text}: "
    while True:
        try:
            answer = input(prompt)
        except EOFError as error:
            raise LicensePoolMetadataError(
                f"no value supplied for license-pool variable {qualified!r}"
            ) from error
        if answer == "":
            if default is not NO_DEFAULT:
                answer = format_license_pool_variable_value(variable, default)
            elif variable.optional:
                return NO_DEFAULT
        try:
            return parse_license_pool_variable_value(variable, answer)
        except LicensePoolMetadataError as error:
            prompt = (
                f"Invalid value for {qualified}: {error}. "
                f"{description}{choices}{optional_text}{default_text}: "
            )


def _write_pool_metadata(pool: Path, metadata: PoolMetadata) -> None:
    target = pool / ".lic-pool"
    body = json.dumps(metadata.to_document(), indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(dir=pool, prefix=".lic-pool.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _register_pool(state: Any, pool: Path, kind: str) -> bool:
    return LicensePoolManager(state).register(pool, kind)


def _registered_pools(state: Any) -> tuple[_RegisteredPool, ...]:
    return tuple(
        _RegisteredPool(pool.path, pool.kind)
        for pool in LicensePoolManager(state).registered_pools()
    )


def _load(state: Any) -> dict[str, Any]:
    if not state.exists(_FILE):
        return {"version": _STATE_VERSION, "pools": {}, "registrations": []}
    value = json.loads(state.read_text(_FILE))
    if not isinstance(value, dict) or not isinstance(value.get("pools"), dict):
        raise LicensePoolError("invalid license-pool state")
    if value.get("version") == 1:
        _upgrade_state_v1(value)
    if value.get("version") == 2:
        _upgrade_state_v2(value)
    if value.get("version") != _STATE_VERSION:
        raise LicensePoolError("invalid license-pool state")
    registrations = value.get("registrations")
    if not isinstance(registrations, list):
        raise LicensePoolError("invalid license-pool state")
    seen: set[str] = set()
    for registration in registrations:
        if (
            not isinstance(registration, dict)
            or not isinstance(registration.get("path"), str)
            or not registration["path"]
            or not isinstance(registration.get("kind"), str)
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]*", registration["kind"]) is None
            or registration["path"] in seen
        ):
            raise LicensePoolError("invalid license-pool state")
        seen.add(registration["path"])
    for entry in value["pools"].values():
        _validate_pool_entry(entry)
    return value


def _claim(
    state: Any,
    requests: list[tuple[str, str, str | None, str]],
    strategy: LicenseStrategy | str = LicenseStrategy.LEAST_RECENTLY_USED,
) -> dict[str, str]:
    assigned, _created = _claim_with_created(state, requests, strategy)
    return assigned


def _claim_with_created(
    state: Any,
    requests: list[tuple[str, str, str | None, str]],
    strategy: LicenseStrategy | str = LicenseStrategy.LEAST_RECENTLY_USED,
) -> tuple[dict[str, str], tuple[tuple[str, str, str], ...]]:
    return _claim_all_with_created(state, requests, (), strategy)


def _claim_all_with_created(
    state: Any,
    requests: list[tuple[str, str, str | None, str]],
    automatic: tuple[_AutomaticRequest, ...] | list[_AutomaticRequest],
    strategy: LicenseStrategy | str = LicenseStrategy.LEAST_RECENTLY_USED,
) -> tuple[dict[str, str], tuple[tuple[str, str, str], ...]]:
    strategy = _coerce_strategy(strategy)
    with state.transaction() as locked:
        registry = _load(locked)
        out: dict[str, str] = {}
        created: list[tuple[str, str, str]] = []
        for _node, pool, clamp, claim in requests:
            entry = registry["pools"].setdefault(pool, _new_pool_entry())
            _validate_pool_entry(entry)
            files = _pool_files(pool)
            if not files:
                raise LicensePoolError(f"license pool is empty: {pool}")
            choice, was_created = _assign_from_pool(
                entry, pool, files, clamp, claim, strategy
            )
            if choice is None:
                detail = (
                    "clamped license is unavailable"
                    if clamp
                    else "no available licenses"
                )
                raise LicensePoolError(f"{detail} in pool {pool}")
            if was_created:
                created.append((pool, choice, claim))
            out[claim] = choice

        for request in automatic:
            entries: list[tuple[str, dict[str, Any], list[str]]] = []
            for pool in request.pools:
                entry = registry["pools"].setdefault(pool, _new_pool_entry())
                _validate_pool_entry(entry)
                entries.append((pool, entry, _pool_files(pool, missing_ok=True)))
            existing = next(
                (
                    (pool, entry, path)
                    for pool, entry, files in entries
                    for path, owner in entry["allocations"].items()
                    if owner == request.claim and path in files
                ),
                None,
            )
            if existing is not None:
                _pool_name, entry, path = existing
                _record_use(entry, path)
                out[request.claim] = path
                continue
            selected: tuple[str, dict[str, Any], str, bool] | None = None
            for pool, entry, files in entries:
                if not files:
                    continue
                choice, was_created = _assign_from_pool(
                    entry,
                    pool,
                    files,
                    request.clamp,
                    request.claim,
                    strategy,
                )
                if choice is not None:
                    selected = (pool, entry, choice, was_created)
                    break
            if selected is None:
                raise LicensePoolError(
                    f"no available license in registered pools for node {request.node}"
                )
            pool, _entry, choice, was_created = selected
            if was_created:
                created.append((pool, choice, request.claim))
            out[request.claim] = choice
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")
        return out, tuple(created)


def _pool_files(pool: str, *, missing_ok: bool = False) -> list[str]:
    try:
        entries = Path(pool).iterdir()
        # An empty file cannot carry a license; stray markers such as a touched
        # `.tst` would otherwise be served. Dotfiles are skipped by pool name,
        # including a dotfile symlink to a real license.
        return sorted(
            str(path.resolve())
            for path in entries
            if path.is_file()
            and not path.name.startswith(".")
            and path.stat().st_size > 0
        )
    except OSError:
        if missing_ok:
            return []
        raise


def _assign_from_pool(
    entry: dict[str, Any],
    pool: str,
    files: list[str],
    clamp: str | None,
    claim: str,
    strategy: LicenseStrategy,
) -> tuple[str | None, bool]:
    target = clamp
    if target and not Path(target).is_absolute():
        target = str((Path(pool) / target).resolve())
    state = PoolState.from_mapping(entry)
    result = selector.select(
        state,
        files=files,
        request=AllocationRequest(claim=claim, clamp=target),
        strategy=strategy,
    )
    if result is None:
        return None, False
    entry.clear()
    entry.update(state.to_mapping())
    return result.path, result.created


def _license_strategy(environ: Mapping[str, str]) -> LicenseStrategy:
    return _coerce_strategy(
        environ.get(
            LICENSE_POOL_STRATEGY_ENVIRONMENT,
            LicenseStrategy.LEAST_RECENTLY_USED.value,
        )
    )


def _coerce_strategy(value: LicenseStrategy | str) -> LicenseStrategy:
    return coerce_strategy(value)


def _new_pool_entry() -> dict[str, Any]:
    return {
        "allocations": {},
        "history": {},
        "clamped": [],
        "round_robin_index": 0,
        "last_used": {},
        "usage_sequence": 0,
    }


def _upgrade_state_v1(registry: dict[str, Any]) -> None:
    pools = registry["pools"]
    assert isinstance(pools, dict)
    for entry in pools.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("history"), dict):
            raise LicensePoolError("invalid license-pool state")
        entry["round_robin_index"] = 0
        entry["last_used"] = {path: 0 for path in entry["history"]}
        entry["usage_sequence"] = 0
    registry["version"] = 2


def _upgrade_state_v2(registry: dict[str, Any]) -> None:
    registry["registrations"] = []
    registry["version"] = _STATE_VERSION


def _validate_pool_entry(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise LicensePoolError("invalid license-pool state")
    mappings = (entry.get("allocations"), entry.get("history"))
    if any(
        not isinstance(mapping, dict)
        or any(
            not isinstance(path, str) or not isinstance(owner, str)
            for path, owner in mapping.items()
        )
        for mapping in mappings
    ):
        raise LicensePoolError("invalid license-pool state")
    clamped = entry.get("clamped")
    last_used = entry.get("last_used")
    if (
        not isinstance(clamped, list)
        or any(not isinstance(path, str) for path in clamped)
        or not isinstance(last_used, dict)
        or any(
            not isinstance(path, str) or type(sequence) is not int or sequence < 0
            for path, sequence in last_used.items()
        )
    ):
        raise LicensePoolError("invalid license-pool state")
    for field in ("round_robin_index", "usage_sequence"):
        value = entry.get(field)
        if type(value) is not int or value < 0:
            raise LicensePoolError("invalid license-pool state")
    if any(sequence > entry["usage_sequence"] for sequence in last_used.values()):
        raise LicensePoolError("invalid license-pool state")


def _select_available(
    entry: dict[str, Any],
    files: list[str],
    free: list[str],
    history: dict[str, str],
    claim: str,
    strategy: LicenseStrategy,
) -> str | None:
    state = PoolState.from_mapping(entry)
    result = selector.select(
        state,
        files=files,
        request=AllocationRequest(claim=claim),
        strategy=strategy,
    )
    entry.clear()
    entry.update(state.to_mapping())
    return result.path if result is not None else None


def _record_use(entry: dict[str, Any], path: str) -> None:
    state = PoolState.from_mapping(entry)
    state.usage_sequence += 1
    state.last_used[path] = state.usage_sequence
    entry.clear()
    entry.update(state.to_mapping())


def _release_workspace(state: Any, workspace: str) -> None:
    with state.transaction() as locked:
        registry = _load(locked)
        for entry in registry["pools"].values():
            entry["allocations"] = {
                path: claim
                for path, claim in entry["allocations"].items()
                if not claim.startswith(workspace + ":")
            }
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")


def _release_claims(state: Any, claims: tuple[tuple[str, str, str], ...]) -> None:
    if not claims:
        return
    with state.transaction() as locked:
        registry = _load(locked)
        for pool, path, claim in claims:
            entry = registry["pools"].get(pool)
            if isinstance(entry, dict) and entry["allocations"].get(path) == claim:
                del entry["allocations"][path]
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")


def _warn_legacy_uuid(api: InvocationAPI, data: dict[str, Any]) -> None:
    """Warn about a topology still carrying the removed top-level `uuid:` field.

    Allocation identity moved to node ``env``. Staying silent would quietly change
    which license a node claims, so name the nodes and the replacement instead.
    """
    nodes = data.get("topology", {}).get("nodes", {})
    if not isinstance(nodes, dict):
        return
    stale = sorted(
        str(name)
        for name, node in nodes.items()
        if isinstance(node, dict) and "uuid" in node
    )
    if stale:
        api.logger.warning(
            "ignoring the removed node field 'uuid' on %s; "
            "move the value to env.%s to keep the same license allocation",
            ", ".join(stale),
            UUID_ENVIRONMENT,
        )


def _claimed_workspaces(state: Any) -> tuple[str, ...]:
    """Return every workspace root the registry currently records a claim for.

    Allocations are stored as ``"<workspace root>:<node>"``, matching the prefix
    match `_release_workspace` uses, so the root is everything before the last
    separator.
    """
    with state.transaction() as locked:
        registry = _load(locked)
        roots = {
            claim.rsplit(":", 1)[0]
            for entry in registry["pools"].values()
            for claim in entry["allocations"].values()
            if ":" in claim
        }
    return tuple(sorted(roots))


def _remove_license_copies(root: Path, contract: Any) -> None:
    """Delete only the copy directories this plugin creates inside one workspace."""
    for directory in (contract.state_directory, _LEGACY_STATE_DIRECTORY):
        shutil.rmtree(root / directory / "licenses", ignore_errors=True)


def _release_all(state: Any) -> None:
    with state.transaction() as locked:
        registry = _load(locked)
        for entry in registry["pools"].values():
            entry["allocations"] = {}
        locked.write_text(_FILE, json.dumps(registry, sort_keys=True) + "\n")


def _lease(pool: str) -> str:
    return "license-pool:" + hashlib.sha256(pool.encode()).hexdigest()


def _copy_to_lab(
    source: Path, lab_dir: Path, claim: str, contract: LicenseContract
) -> Path:
    target = _copy_path(lab_dir, claim, source.name, contract)
    target_dir = target.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _copy_path(
    lab_dir: Path, claim: str, filename: str, contract: LicenseContract
) -> Path:
    return (
        lab_dir
        / contract.state_directory
        / "licenses"
        / hashlib.sha256(claim.encode()).hexdigest()
        / filename
    )


def _remove_empty_copy_parents(directory: Path) -> None:
    for candidate in (directory, directory.parent):
        try:
            candidate.rmdir()
        except OSError:
            break
