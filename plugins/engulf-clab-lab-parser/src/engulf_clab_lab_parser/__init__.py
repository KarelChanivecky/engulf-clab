from .plugin import TopologyPlugin
from .session import (
    TOPOLOGY_CONTEXT,
    WRITER_TEMP_PREFIX,
    TopologySession,
    derived_topology_path,
    editor,
    load_topology,
    topology_path_from_args,
)

plugin = TopologyPlugin()
__all__ = [
    "TOPOLOGY_CONTEXT",
    "WRITER_TEMP_PREFIX",
    "TopologyPlugin",
    "TopologySession",
    "derived_topology_path",
    "editor",
    "load_topology",
    "plugin",
    "topology_path_from_args",
]
