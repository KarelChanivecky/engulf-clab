# engulf-clab-ensure-vrnetlab

Prepares the vrnetlab checkout used by `engulf-clab-vrnetlab-build`. Install it with
`python -m pip install engulf-clab-ensure-vrnetlab`; installing the vrnetlab
builder or `engulf-clab-all-plugins` installs it automatically.

The plugin activates for `deploy` only when at least one node has a nonempty
`ECLAB_VRNETLAB_TYPE` environment value. Editions derive this prefix from their
short product name, falling back to full product metadata; for example, a short
product name of `acme clab` uses `ACME_CLAB_VRNETLAB_TYPE`.

For an opted-in deployment, the plugin checks that `docker`, `qemu-img`, and
`qemu-system-x86_64` are on `PATH` before provisioning the checkout.

The opt-in is analyzed without side effects. Deployments with no matching node,
all non-deploy commands, and help do not provision or update vrnetlab. A
configured image source alone does not activate the plugin; the node type field
is the explicit feature marker.

```yaml
topology:
  nodes:
    router:
      image: vrnetlab/vr-example:1.0
      env:
        ECLAB_VRNETLAB_TYPE: vendor/router
```

## Invocation environment

| Variable | Meaning |
| --- | --- |
| `VRNETLAB_DIR` | Existing valid vrnetlab checkout. |
| `VRNETLAB_REPO` | Managed clone source; default `https://github.com/srl-labs/vrnetlab.git`. |
| `VRNETLAB_UPDATE=1` | Check a Git checkout for updates, at most once daily. |
| `VRNETLAB_VERSION` | Clamp to a tag, commit, or Git revision; also enables checking. |

Resolution order is `VRNETLAB_DIR`, a managed user-state checkout, then a new
managed clone. Invalid configured paths are ignored with a diagnostic; an
invalid existing managed checkout is never overwritten. Managed cloning and
updates are serialized by a user-scoped lease.

Git updates prefer the highest version-style release tag reachable from the
checkout branch, or fast-forward by commit when no release tags exist. Non-Git
checkouts are not changed; dirty Git checkouts are rejected rather than reset.

The resolved checkout is published as context `engulf_clab.vrnetlab.path` for
the vrnetlab build plugin. This plugin itself does not build images.

## Checkout validation and state

A valid checkout is a directory containing `common/vrnetlab.py`. This plugin is
vendor-neutral and does not require a particular `vendor/type` builder during
checkout selection; the build plugin validates the requested builder directory
later.

Configured `VRNETLAB_DIR` takes precedence. Otherwise a valid checkout in
Engulf user state is reused or the configured/default repository is cloned into
a staged sibling and published atomically. An invalid configured path emits a
diagnostic and falls through; an invalid existing managed path is never
overwritten. A user-scoped repository lease serializes provisioning/update
across lab workspaces.

Update/clamp behavior comes from `engulf-clab-ensure-checkout`: checks are
opt-in and at most daily for the same request, dirty worktrees are rejected,
release-style tags are preferred, and branches update only by fast-forward.
Existing valid non-Git directories are not modified. The plugin never resets,
cleans, or repairs a checkout.

After preparation, the checkout path is published only in invocation context;
it is not written into the source topology. The downstream builder consumes the
context, validates `vendor/type`, selects the qcow2/archive source, and performs
Docker/Make work.

## Troubleshooting

- Confirm the active launcher's help shows both ensure-vrnetlab and
  vrnetlab-build, and confirm the node uses the prefix displayed by that
  launcher.
- Validate `VRNETLAB_DIR/common/vrnetlab.py` when supplying a checkout.
- Install Docker and QEMU commands in the same `PATH` visible to the local CLI
  or MCP service; local shell availability does not prove service availability.
- For dirty/update failures, inspect Git state and resolve it manually. Do not
  expect the plugin to discard changes.
- For a missing builder, continue with the build plugin and inspect
  `<checkout>/<vendor>/<type>/Makefile`; checkout validity alone does not prove
  that builder exists.
- Under MCP, configure checkout controls and topology-referenced image-source
  paths service-side; callers cannot override protected inputs.
