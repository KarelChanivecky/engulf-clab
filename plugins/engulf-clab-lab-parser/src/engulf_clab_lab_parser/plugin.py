from __future__ import annotations
from engulf_api import InvocationAPI
from engulf_executable_wrapper_api import BeforeCallEvent, CallContribution, CallMode, ExecutableWrapperPlugin, PreparedCallEvent
from .session import TOPOLOGY_CONTEXT, TopologyError, TopologySession, load_topology, topology_path_from_args
class TopologyPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.lab_parser"; priority = 100; context_writes = frozenset({TOPOLOGY_CONTEXT})
    def analyze_call(self, event: BeforeCallEvent, api: InvocationAPI) -> CallContribution | None:
        if event.mode is CallMode.HELP or not event.wrapper_args or event.wrapper_args[0] != "deploy": return None
        try: load_topology(topology_path_from_args(tuple(event.wrapper_args[1:])))
        except (TopologyError, OSError) as error: api.logger.error("%s", error); return CallContribution(preempt_exit_code=1)
        return None
    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not event.wrapper_args or event.wrapper_args[0] != "deploy": return
        path = topology_path_from_args(tuple(event.wrapper_args[1:])); api.set_context(TOPOLOGY_CONTEXT, TopologySession(path, load_topology(path)))
