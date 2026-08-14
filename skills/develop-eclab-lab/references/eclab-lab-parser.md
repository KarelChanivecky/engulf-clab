# engulf-clab-lab-parser

Provides the shared topology session used by plugins that read or defer changes
to a Containerlab YAML file. Install it as a dependency of a topology-aware
plugin; `engulf-clab-all-plugins` installs it automatically.

For `deploy`, the plugin loads the selected `-t` / `--topo` / `--topology` YAML
once and publishes an immutable original document plus a mutation editor in
Engulf context. It has no YAML extension fields and no environment variables for
lab authors.

Plugin authors use the session through `engulf_clab_lab_parser`:

```python
from engulf_clab_lab_parser import editor

mutation = editor(api, "com.example.plugin")
mutation.modify(("topology", "nodes", "router", "license"), "/path/license.lic")
mutation.delete(("topology", "nodes", "wan", "labels", "ECLAB_DHCP_WAN"))
mutation.add(("topology", "nodes", "client", "labels", "role"), "client")
```

Mutations are deferred: chained plugins continue to see the original topology.
The collector plugin applies them later. Deletes override descendant modifications
and additions; modifications and additions create missing mapping parents; list
additions insert at the supplied integer index. Conflicting modifications at the
same path are rejected.
