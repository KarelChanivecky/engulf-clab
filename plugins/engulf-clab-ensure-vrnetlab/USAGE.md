# engulf-clab-ensure-vrnetlab

Install directly with `python -m pip install engulf-clab-ensure-vrnetlab`, or
through `engulf-clab-all-plugins`; the vrnetlab builder also installs it as a
dependency.

It prepares the checkout consumed by `engulf-clab-vrnetlab-build` and activates
for deploy or single-source redeploy when a node explicitly opts in. The
`ECLAB_VRNETLAB_TYPE` node variable is declared by an installed source provider,
such as `engulf-clab-vrnetlab-static-image-provider`:

```yaml
topology:
  nodes:
    router:
      image: vrnetlab/vr-example:1.0
      env:
        ECLAB_VRNETLAB_TYPE: vendor/router
```

The fixed `ECLAB_VRNETLAB_TYPE` marker is portable across editions. A
configured image source alone does not activate provisioning. Opted-in
deployments require `docker`, `qemu-img`, and `qemu-system-x86_64` on `PATH`.
This plugin only prepares a checkout. The active source provider selects or
creates an input path, and the downstream builder validates the requested
builder and performs the Docker/Make work.

## Checkout selection

| CLI option | Persistent default | Meaning |
| --- | --- | --- |
| `--eclab-vrnetlab-dir DIR` | `VRNETLAB_DIR` | Existing checkout. |
| `--eclab-vrnetlab-repo URL` | `VRNETLAB_REPO` | Managed clone source; defaults to `https://github.com/KarelChanivecky/vrnetlab/tree/master`. GitHub `/tree/<branch>` URLs select that branch. |
| `--eclab-vrnetlab-update` | `VRNETLAB_UPDATE` | Check for updates at most daily per checkout/request. |
| `--eclab-vrnetlab-version REV` | `VRNETLAB_VERSION` | Pin a tag, commit, or revision and enable checking. |

The CLI form wins. Resolution uses a valid configured directory, then a valid
managed user-state checkout, then a new managed clone. A valid checkout
contains `common/vrnetlab.py`; the build plugin later validates the requested
`vendor/type` directory and `Makefile`.

Managed cloning is staged and serialized across workspaces. Update and clamp
behavior comes from `engulf-clab-ensure-checkout`. Update/version controls apply
to clean configured Git checkouts as well as the managed checkout. Update selects the highest reachable version-shaped tag, or
fast-forwards the branch when none exists. A version clamp must resolve to a
commit and is checked out detached. A checkout without an origin remains at its
current revision. Dirty worktrees are rejected. Non-Git checkouts are left
alone, and an invalid existing managed path is never overwritten or repaired.

The managed checkout and update metadata are durable user-scoped cache. They remain
available if a later plugin cannot prepare the call; invocation-scoped published
contexts are discarded with that failed invocation.

The resolved checkout is available only to the current invocation and is not
written into the source topology. If another plugin stops preprocessing before
the runtime schema generator, the original failure remains authoritative and
this plugin suppresses the otherwise-secondary unused source-context warning.

## Troubleshooting and security

- Confirm a source provider declares a nonempty `ECLAB_VRNETLAB_TYPE`, and that
  the provider and builder plugins are active in the same launcher.
- Validate `<DIR>/common/vrnetlab.py` for an explicit directory.
- Install Docker and QEMU tools in the environment visible to the actual CLI or
  MCP service; shell visibility does not prove service visibility.
- Resolve dirty/update failures manually. For a missing builder, continue with
  the build plugin and inspect `<checkout>/<vendor>/<type>/Makefile`; checkout
  validity alone does not prove that builder exists.
- Under MCP, configure checkout controls and topology-referenced image paths in
  the root-owned profile; callers cannot override protected inputs.

## Runtime schema discovery

The plugin records its checkout and node opt-in controls, publishes the selected
source during `before_goal`, and snapshots this packaged `USAGE.md` before the
runtime schema generator runs last. The generator therefore needs to infer the
vrnetlab source only when this ensure plugin is absent.
