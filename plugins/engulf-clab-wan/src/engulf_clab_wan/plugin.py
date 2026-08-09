from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from engulf_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallMode,
    OutcomeKind,
    Plugin,
    PluginAPI,
)

from .errors import WanError
from .logging import info
from .networks import cleanup_dhcp_wan_bridges, setup_dhcp_wan_bridges
from .topology import load_topology, topology_path_from_args

_TOPOLOGY_PATH = "dev.karel.engulf_clab.wan.topology_path"


class WanPlugin(Plugin):
    plugin_id = "dev.karel.engulf_clab.wan"
    priority = 50
    context_reads = frozenset({_TOPOLOGY_PATH})
    context_writes = frozenset({_TOPOLOGY_PATH})

    def help(self) -> str:
        return (
            "  FCLAB_DHCP_WAN   Manage labeled bridge nodes as DHCP/NAT WANs\n"
            "                    before deploy and after successful destroy"
        )

    def before_call(self, event: BeforeCallEvent, api: PluginAPI) -> None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return

        command, *rest = event.wrapper_args
        if command == "deploy":
            self._setup_before_deploy(tuple(rest), api)
        elif command == "destroy":
            self._remember_destroy_topology(tuple(rest), api)

    def after_call(self, event: AfterCallEvent, api: PluginAPI) -> None:
        if event.mode is CallMode.HELP or not event.wrapper_args:
            return
        if event.wrapper_args[0] != "destroy":
            return
        if event.outcome.kind is not OutcomeKind.COMPLETED or event.outcome.exit_code != 0:
            return

        topology_path = api.get_context(_TOPOLOGY_PATH)
        if isinstance(topology_path, str):
            cleanup_dhcp_wan_bridges(Path(topology_path))

    def _setup_before_deploy(self, args: tuple[str, ...], api: PluginAPI) -> None:
        try:
            topology_path = topology_path_from_args(args)
            topology_data = load_topology(topology_path)
            info(f"using topology {topology_path}")
            setup_dhcp_wan_bridges(topology_path, topology_data)
        except (WanError, OSError, subprocess.CalledProcessError) as error:
            print(f"engulf-clab-wan: error: {error}", file=sys.stderr, flush=True)
            api.preempt(1)

    def _remember_destroy_topology(self, args: tuple[str, ...], api: PluginAPI) -> None:
        try:
            topology_path = topology_path_from_args(args)
        except WanError:
            return
        api.set_context(_TOPOLOGY_PATH, str(topology_path))
