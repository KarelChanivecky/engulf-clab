# engulf-clab-ensure-vrnetlab

`engulf-clab-ensure-vrnetlab` prepares the vrnetlab checkout consumed by the
`engulf-clab-vrnetlab` image-build plugin.

The plugin activates before `engulf-clab deploy` only when the selected topology
contains a node with a nonempty `ENGULF_CLAB_VRNETLAB_TYPE` value. An edition
derives the prefix from its `display_name` (for example, `acme-clab` uses
`ACME_CLAB_VRNETLAB_TYPE`). It resolves the
checkout in this order:

1. A valid checkout named by `VRNETLAB_DIR`.
2. The plugin's user-scoped Engulf state checkout.
3. A new clone of `VRNETLAB_REPO` into that managed location.

`VRNETLAB_REPO` defaults to:

```text
https://github.com/srl-labs/vrnetlab.git
```

An invalid `VRNETLAB_DIR` is reported and ignored. An existing but invalid
managed checkout is not overwritten; remove it explicitly before retrying.
Existing valid checkouts are never pulled, reset, or cleaned.

After resolution, the plugin publishes the canonical path in Engulf context:

```text
engulf_clab.vrnetlab.path
```

The build plugin has a hard dependency on this plugin and consumes that context
after ensure-vrnetlab completes. Clone operations are staged in a temporary
sibling directory so a failed clone does not leave the managed target partially
populated.

Managed checkout discovery and cloning run under the application/user lease
`repository-cache:vrnetlab`. This serializes cooperating deployments while the
checkout tree is inspected or created; the temporary staging directory still
protects against interrupted clone publication.
