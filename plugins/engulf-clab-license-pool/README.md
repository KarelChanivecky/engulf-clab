# engulf-clab-license-pool

Allocates license files from a shared directory pool and writes a lab-local copy
into the temporary topology before deploy. Install it with
`python -m pip install engulf-clab-license-pool`, or through
`engulf-clab-all-plugins`.

## YAML and invocation environment

Set a node's Containerlab `license` field to `$POOL_NAME`. Set the invocation
environment variable with that exact name to a directory of license files.

```yaml
topology:
  nodes:
    fgt:
      image: vrnetlab/vr-fortios:latest
      uuid: 4c1a8ee8-6ef7-4501-bfc1-6b082c3120f0
      license: $FORTIGATE_LICENSES
      env:
        ECLAB_LIC_CLAMP: serial-0001.lic
```

```bash
export FORTIGATE_LICENSES=$PWD/licenses/fortigate
eclab deploy -t lab.clab.yml
```

| YAML / environment item | Meaning |
| --- | --- |
| `license: $POOL_NAME` | Select from the directory named by `$POOL_NAME` in the invocation environment. |
| `uuid` | Recommended stable node identity. Without it, the node name is used. |
| `env.ECLAB_LIC_CLAMP` | Optional required filename or path within the pool. Deploy fails if it is allocated. |
| `POOL_NAME=/path/to/licenses` | Invocation environment variable; value must be a directory. |

Frozen shared labs use `license: __ECLAB_LICENSE_PROMPT__` instead. At deploy,
the plugin asks for a license file, pool directory, or `$VARIABLE`. For
non-interactive use set `ECLAB_LICENSE`, or `ECLAB_LICENSE_<NODE_NAME>` for one
node. A directory is allocated using the same shared pool mechanism; a file is
copied only into the running lab's generated topology.

## Allocation and cleanup

Allocations are globally coordinated in user state and guarded by leases, so
multiple labs can share a pool. Never-used licenses are assigned first;
previously assigned licenses are preferred for the same node identity; clamped
licenses are considered last for ordinary allocation. The selected file is
copied under `.engulf-clab/licenses/` beside the topology and the generated
topology references that copy.

A successful `destroy` releases that workspace's claims and removes its copied
licenses. `destroy -a` / `destroy --all` releases every recorded allocation.
