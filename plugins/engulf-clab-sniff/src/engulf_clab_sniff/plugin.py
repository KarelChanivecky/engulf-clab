from __future__ import annotations

import os

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, RegistrationAPI
from engulf_clab_schema_api import (
    SCHEMA_CONTEXTS,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import CompletionRegistry, HelpAPI

from .command import main as run_sniff
from .completion import register_sniff_completions
from .wireshark_access import add_dumpcap_capture_group

PLUGIN_ID = "engulf_clab.sniff"

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_sniff")
    .add_command("sniff", "Capture packets on the direct link between two lab nodes.")
    .add_cli_argument(
        "sniff",
        "NODE1",
        "Select the node whose network namespace tcpdump joins.",
        values=ValueType.STRING,
    )
    .add_cli_argument(
        "sniff",
        "NODE2",
        "Select a node directly connected to NODE1.",
        values=ValueType.STRING,
    )
    .add_cli_flag(
        ("-t", "--topology"),
        "Select a topology; otherwise require one in the current directory.",
        command="sniff",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--interface",
        "Choose NODE1's interface when the node pair has multiple direct links.",
        command="sniff",
        values=ValueType.STRING,
    )
    .add_cli_flag(
        "--write",
        "Write a new pcap file to this host path instead of printing packets.",
        command="sniff",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--wireshark",
        "Open Wireshark with a managed capture that supports Stop and Restart.",
        command="sniff",
    )
    .add_cli_argument(
        "sniff",
        "TCPDUMP_ARGUMENT",
        "Pass a safe tcpdump option or a BPF filter token.",
        values=ValueType.STRING,
        required=False,
        repeatable=True,
    )
    .annotate(
        "sniff",
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        host_tools=("docker",),
        privilege=Privilege.CONTAINER_RUNTIME,
        examples=(
            "eclab sniff router client -nn -Q in tcp port 179",
            "eclab sniff router client --write captures/bgp.pcap -- -s 0",
            "eclab sniff router client --wireshark tcp port 179",
        ),
    )
    .annotate(
        "-t",
        commands=("sniff",),
        path_base=PathBase.INVOCATION_DIRECTORY,
    )
    .annotate(
        "--interface",
        commands=("sniff",),
        implies=("selects an interface from NODE1 to NODE2",),
    )
    .annotate(
        "--write",
        commands=("sniff",),
        path_base=PathBase.INVOCATION_DIRECTORY,
        implies=("the output file must not already exist",),
    )
    .annotate(
        "--wireshark",
        commands=("sniff",),
        requires=("Wireshark and dumpcap must be executable on the host",),
        implies=("cannot be combined with --write",),
        host_tools=("wireshark", "dumpcap"),
    )
    .require_host_tool(
        "docker",
        "Docker starts a disposable tcpdump helper in NODE1's network namespace.",
        commands=("sniff",),
    )
    .require_privilege(
        Privilege.CONTAINER_RUNTIME,
        "The caller must be authorized to inspect and join Docker container network namespaces.",
        commands=("sniff",),
    )
    .use_case("Inspect traffic crossing one direct Containerlab node-to-node link.")
    .reject(
        "Only allowlisted tcpdump options are passed; choose the link through the node pair."
    )
    .route(
        "capture-node-link-traffic",
        "USAGE.md",
        "Read capture scope, supported options, output files, and namespace requirements.",
    )
    .refer("USAGE.md")
)


class SniffPlugin(SchemaBackedPlugin):
    """Capture a selected Containerlab node link using a transient helper."""

    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 200
    context_reads = SCHEMA_CONTEXTS
    context_writes = SCHEMA_CONTEXTS

    def register_completions(
        self,
        registry: CompletionRegistry,
        api: RegistrationAPI,
    ) -> None:
        register_sniff_completions(registry, api)

    def before_goal(
        self, invocation: Invocation, api: BeforeGoalAPI
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if invocation.arguments and invocation.arguments[0] == "sudoless":
            if os.name == "posix" and hasattr(os, "getuid") and os.getuid() != 0:
                try:
                    import pwd

                    username = pwd.getpwuid(os.getuid()).pw_name
                    setup = add_dumpcap_capture_group(username, invocation.environment)
                except (ImportError, KeyError, OSError) as error:
                    api.logger.warning(
                        "could not inspect Wireshark capture access: %s", error
                    )
                else:
                    if setup.warning is not None:
                        api.logger.warning(
                            "Wireshark capture access: %s", setup.warning
                        )
                    elif setup.group_added is not None:
                        api.logger.warning(
                            "added user %s to Wireshark capture group %s, granting "
                            "host packet-capture access; log out and back in before "
                            "using --wireshark",
                            username,
                            setup.group_added,
                        )
            return None
        if not invocation.arguments or invocation.arguments[0] != "sniff":
            return None
        application_name = api.application.short_product_name or api.application.product
        exit_code = run_sniff(
            invocation.arguments[1:],
            cwd=invocation.cwd,
            environment=invocation.environment,
            program=f"{application_name} sniff",
            logger=api.logger,
        )
        return GoalResult.completed(exit_code=exit_code)

    def help(self, api: HelpAPI) -> str:
        launcher = api.application.short_product_name or api.application.product
        return (
            "  sniff [--topology FILE] NODE1 NODE2 [--interface IFACE] "
            "[--write FILE | --wireshark] [--] [tcpdump options] [BPF filter]\n"
            "    Captures the direct link from NODE1 with a disposable tcpdump helper; "
            "--wireshark opens a managed live capture with GUI Stop and Restart. "
            f"Run {launcher} sudoless to join a preconfigured Wireshark capture group. "
            "Completion lists "
            "nodes, neighbors, and safe tcpdump filters."
        )
