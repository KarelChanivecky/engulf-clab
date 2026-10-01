from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from engulf_api import (
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    PluginLogger,
    StateScope,
)
from engulf_clab_license_pool_lib import LicensePoolError, LicensePoolManager
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    SCHEMA_SOURCE_CONTEXT,
    SCHEMA_VRNETLAB_SOURCE_CONTEXT,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    RecordedPluginSchema,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
    schema_registry,
)
from engulf_clab_vrnetlab_build_api import VRNETLAB_SOURCE_PROVENANCE_CONTEXT
from engulf_docker_image_api import DOCKER_IMAGE_PROVENANCE_CONTEXT
from engulf_executable_wrapper_api import HelpAPI

from .command import main as run_freeze_command
from .defrost import lease as defrost_lease
from .defrost import main as run_defrost_command

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.freeze", package="engulf_clab_freeze")
    .add_command("freeze", "Create a sanitized, portable archive from a lab topology.")
    .add_cli_argument(
        "freeze",
        "LAB_DIR",
        "Select the directory containing one source topology; defaults to the current directory.",
        values=ValueType.DIRECTORY_PATH,
        required=False,
        default=".",
    )
    .add_cli_flag(
        ("-t", "--eclab-topology"),
        "Select the source topology file.",
        command="freeze",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--eclab-output",
        "Write the package here: .tar.gz/.tgz for lean, or .run with runtime/offline packaging.",
        command="freeze",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--eclab-offline",
        "Create a self-extracting .run with the runtime, tools, and lab images for offline use.",
        command="freeze",
    )
    .add_cli_flag(
        "--eclab-with-runtime",
        "Create a self-extracting .run with runtime/ and lab.tgz; defrost.sh builds the venv and prompts for recipient values.",
        command="freeze",
    )
    .add_cli_flag(
        "--eclab-external-image",
        "Declare an image that the recipient supplies; repeat for additional dependencies.",
        command="freeze",
        values=ValueType.IMAGE_REFERENCE,
        repeatable=True,
    )
    .add_cli_flag(
        "--eclab-bundle-image",
        "Export an image into an offline archive.",
        command="freeze",
        values=ValueType.IMAGE_REFERENCE,
        repeatable=True,
    )
    .add_cli_flag(
        "--eclab-include-pki-secrets",
        "Include exportable PKI identities when the PKI contributor is installed.",
        command="freeze",
    )
    .add_cli_flag(
        "--eclab-pki-passphrase-file",
        "Read the PKI export passphrase from an owner-private file.",
        command="freeze",
        values=ValueType.FILE_PATH,
    )
    .annotate(
        "freeze",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=("normal Containerlab execution is preempted",),
        examples=("eclab freeze labs/demo --eclab-output share.tar.gz",),
    )
    .annotate(
        "LAB_DIR",
        commands=("freeze",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("-t",),
    )
    .annotate(
        "-t",
        commands=("freeze",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        conflicts_with=("LAB_DIR",),
    )
    .annotate(
        "--eclab-output",
        commands=("freeze", "defrost"),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--eclab-offline",
        commands=("freeze",),
        conflicts_with=("--eclab-external-image",),
        implies=(
            "bundle runtime/tools and images whose rebuild may require network access",
        ),
    )
    .annotate("--eclab-with-runtime", commands=("freeze",))
    .annotate(
        "--eclab-external-image",
        commands=("freeze",),
        conflicts_with=("--eclab-offline",),
    )
    .annotate(
        "--eclab-bundle-image",
        commands=("freeze",),
        requires=("--eclab-offline",),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
    )
    .add_command(
        "defrost",
        "Expand a frozen archive into a runnable lab directory and restore its env initializer.",
    )
    .add_cli_argument(
        "defrost",
        "ARCHIVE",
        "Select the frozen archive to expand.",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--eclab-output",
        "Write the lab into this directory.",
        command="defrost",
        values=ValueType.DIRECTORY_PATH,
    )
    .add_cli_flag(
        "--eclab-force",
        "Replace a directory an earlier defrost created at the destination.",
        command="defrost",
    )
    .add_cli_flag(
        "--eclab-license",
        "Answer one frozen license prompt as NODE=VALUE, or every prompt as VALUE.",
        command="defrost",
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_cli_flag(
        "--eclab-env",
        "Provide a topology environment value to the recipient initializer as NAME=VALUE.",
        command="defrost",
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_cli_flag(
        "--eclab-no-license-prompt",
        "Keep frozen license markers instead of asking for paths.",
        command="defrost",
    )
    .add_cli_flag(
        "--eclab-no-runtime",
        "Skip attaching the prepared venv; the restored lab launcher handles runtime setup.",
        command="defrost",
    )
    .add_cli_flag(
        "--eclab-no-images",
        "Skip selection of bundled Docker image archives.",
        command="defrost",
    )
    .add_cli_flag(
        "--eclab-skip-env-init",
        "Do not run the archive's recipient environment initializer.",
        command="defrost",
    )
    .add_cli_flag(
        "--eclab-pki-authority",
        "Resolve one frozen PKI binding as BINDING=REF.",
        command="defrost",
        values=ValueType.STRING,
        repeatable=True,
    )
    .add_cli_flag(
        "--eclab-no-pki-prompt",
        "Keep unresolved PKI bindings as actionable manifest markers.",
        command="defrost",
    )
    .add_cli_flag(
        "--eclab-pki-passphrase-file",
        "Read the PKI import passphrase from an owner-private file.",
        command="defrost",
        values=ValueType.FILE_PATH,
    )
    .annotate(
        "defrost",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        implies=("normal Containerlab execution is preempted",),
        examples=("eclab defrost share.tar.gz --eclab-output labs/demo",),
    )
    .annotate(
        "ARCHIVE",
        commands=("defrost",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--eclab-force",
        commands=("defrost",),
        requires=("the destination holds an earlier defrost record",),
    )
    .annotate(
        "--eclab-license",
        commands=("defrost",),
        path_base=PathBase.LICENSE_POOL,
        conflicts_with=("--eclab-no-license-prompt",),
    )
    .annotate(
        "--eclab-env",
        commands=("defrost",),
        conflicts_with=("--eclab-skip-env-init",),
    )
    .annotate(
        "--eclab-no-license-prompt",
        commands=("defrost",),
        implies=("deploy resolves every frozen license instead",),
    )
    .annotate(
        "--eclab-no-runtime",
        commands=("defrost",),
        implies=("the restored lab launcher handles runtime setup at first use",),
    )
    .use_case(
        "Create a sanitized portable archive without deploying or destroying the lab."
    )
    .use_case(
        "Use the lean default for recipient image inputs, or --eclab-offline to bundle images."
    )
    .use_case(
        "Use --eclab-with-runtime to create a bundle whose defrost.sh uses its bundled runtime and runs the normal license and environment setup."
    )
    .use_case(
        "Expand a received archive into a lab with local licenses, images, and runtime."
    )
    .reject(
        "Do not assume external files or secrets are dereferenced into the archive."
    )
    .route(
        "freeze-lab",
        "USAGE.md",
        "Read sanitization, archive selection, and offline guarantees.",
    )
    .route(
        "defrost-lab",
        "USAGE.md",
        "Read expansion, license answers, image selection, and runtime preparation.",
    )
    .refer("USAGE.md")
)


class FreezePlugin(SchemaBackedPlugin):
    """Own the freeze and defrost control commands before the Containerlab goal runs."""

    plugin_id = "engulf_clab.freeze"
    schema = PLUGIN_SCHEMA
    priority = 200
    context_reads = SCHEMA_CONTEXTS | frozenset(
        {
            SCHEMA_SOURCE_CONTEXT,
            SCHEMA_VRNETLAB_SOURCE_CONTEXT,
            DOCKER_IMAGE_PROVENANCE_CONTEXT,
            VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
        }
    )
    context_writes = SCHEMA_CONTEXTS

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if not invocation.arguments:
            return None
        if invocation.arguments[0] == "defrost":
            self._acknowledge_schema_sources(api)
            return self._defrost(invocation, api)
        if invocation.arguments[0] != "freeze":
            return None
        self._acknowledge_schema_sources(api)
        workspace = api.state(StateScope.WORKSPACE)
        registry = schema_registry(api)
        requirements = tuple(
            requirement
            for contribution in registry.contributions
            if isinstance(contribution.entry, RecordedPluginSchema)
            for requirement in contribution.entry.requirements
        )
        offline = "--eclab-offline" in invocation.arguments[1:]
        application_name = api.application.short_product_name or api.application.product
        user_state = api.state(StateScope.USER)
        # Fixed regardless of edition, so two differently-branded editions
        # freezing the same workspace concurrently actually block each other.
        leases = [f"eclab-freeze:{workspace.root}"]
        if offline:
            leases.extend(
                ("repository-cache:containerlab", "repository-cache:vrnetlab")
            )
        with api.leases(tuple(leases)):
            exit_code = run_freeze_command(
                list(invocation.arguments[1:]),
                workspace,
                user_state=user_state,
                program=f"{application_name} freeze",
                application_name=application_name,
                logger=api.logger,
                environment=invocation.environment,
                requirements=requirements,
            )
        return GoalResult.completed(exit_code=exit_code)

    @staticmethod
    def _acknowledge_schema_sources(api: BeforeGoalAPI) -> None:
        """Consume terminal schema inputs when a control command preempts it."""
        api.get_context(SCHEMA_SOURCE_CONTEXT)
        api.get_context(SCHEMA_VRNETLAB_SOURCE_CONTEXT)

    def _defrost(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object]:
        """Expand one archive under a lease covering only its destination."""
        arguments = list(invocation.arguments[1:])
        application_name = api.application.short_product_name or api.application.product
        # Fixed regardless of edition, for the same reason the freeze lease is:
        # two differently-branded editions writing one destination must block.
        with api.leases((defrost_lease(arguments, invocation.cwd),)):
            user_state = api.state(StateScope.USER)
            try:
                pools_registered = bool(
                    LicensePoolManager(user_state).registered_pools()
                )
            except (LicensePoolError, OSError, ValueError) as error:
                api.logger.warning(
                    "could not check registered license pools: %s", error
                )
                pools_registered = None
            exit_code = run_defrost_command(
                arguments,
                program=f"{application_name} defrost",
                application_name=application_name,
                logger=api.logger,
                environment=invocation.environment,
                cwd=invocation.cwd,
                user_state=user_state.directory,
                license_pools_registered=pools_registered,
                setup_license_pool=(
                    None
                    if pools_registered is not False
                    else lambda: _offer_license_pool_setup(
                        invocation, application_name, api.logger
                    )
                ),
            )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  freeze [LAB_DIR | -t TOPOLOGY] [--eclab-output PACKAGE] [--eclab-with-runtime | --eclab-offline]  "
            "Create a sanitized portable lab archive\n"
            "    Default: record compatibility; leave runtime and images to the recipient.\n"
            "    --eclab-with-runtime: self-extracting .run with runtime/, lab.tgz, and defrost.sh; --eclab-offline: self-extracting .run with runtime, tools, images.\n"
            "    --eclab-external-image IMAGE (non-offline) / --eclab-bundle-image IMAGE (offline).\n"
            "  defrost ARCHIVE [--eclab-output DIRECTORY] [--eclab-pki-authority BINDING=REF]  "
            "Expand a frozen archive into a runnable lab"
        )


def _offer_license_pool_setup(
    invocation: Invocation, application_name: str, logger: PluginLogger
) -> bool:
    """Create and initialize a pool directory when a frozen lab has no pool."""
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(
            "\nNo license pool is registered. Would you like to set one up now? [y/N]: "
        )
    except EOFError:
        return False
    if answer.strip().casefold() not in {"y", "yes"}:
        return False
    try:
        selected = input(
            "Where should the license-pool directory be created? "
            "(you can add license files afterward; empty to cancel): "
        ).strip()
    except EOFError:
        return False
    if not selected:
        return False

    caller_cwd = Path(
        invocation.environment.get("ECLAB_FREEZE_CALLER_CWD", str(invocation.cwd))
    ).expanduser()
    if not caller_cwd.is_absolute():
        caller_cwd = invocation.cwd / caller_cwd
    caller_cwd = caller_cwd.resolve()
    # Expand `~` using the invocation environment. Path.expanduser() only
    # consults the current process environment, which can differ when defrost
    # was entered through a bundled runtime or an edition launcher.
    if selected == "~" or selected.startswith("~/"):
        home = invocation.environment.get("HOME") or os.environ.get("HOME")
        pool = Path(home) / selected[2:] if home else Path(selected).expanduser()
    else:
        pool = Path(selected).expanduser()
    if not pool.is_absolute():
        pool = caller_cwd / pool
    pool = pool.resolve()

    launcher_arg = sys.argv[0]
    launcher = Path(launcher_arg).expanduser()
    if not launcher.is_absolute():
        located = shutil.which(launcher_arg)
        launcher = Path(located) if located else caller_cwd / launcher
    launcher = launcher.resolve()
    if not launcher.is_file():
        logger.warning("could not locate this edition's launcher to register the pool")
        return False

    try:
        pool.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.warning("could not create license-pool directory %s: %s", pool, error)
        return False

    environment = os.environ.copy()
    environment.update(invocation.environment)
    try:
        result = subprocess.run(
            [str(launcher), "init-license-pool", str(pool)],
            cwd=pool,
            env=environment,
            check=False,
        )
    except OSError:
        logger.warning(
            "could not start the license-pool registration command; you can register one later with %s init-license-pool PATH",
            application_name,
        )
        return False
    if result.returncode:
        logger.warning(
            "license-pool setup did not complete; you can register one later with %s init-license-pool PATH",
            application_name,
        )
        return False
    logger.info(
        "license pool initialized; add entitled license files before choosing auto at deployment"
    )
    return True
