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
