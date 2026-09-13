from .plugin import TopologyPlugin
from .session import (
    TOPOLOGY_CONTEXT,
    WRITER_TEMP_PREFIX,
    TopologyError,
    TopologySession,
    derived_topology_path,
    editor,
    is_topology_mutation_command,
    load_topology,
    topology_path_from_args,
)

plugin = TopologyPlugin()
__all__ = [
    "TOPOLOGY_CONTEXT",
    "WRITER_TEMP_PREFIX",
    "TopologyError",
    "TopologyPlugin",
    "TopologySession",
    "derived_topology_path",
    "editor",
    "is_topology_mutation_command",
    "load_topology",
    "plugin",
    "topology_path_from_args",
]
