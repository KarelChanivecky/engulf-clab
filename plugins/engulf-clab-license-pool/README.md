# engulf-clab-license-pool

Allocates license files from a shared directory pool and writes a lab-local copy
into the temporary topology before deploy. Install it with
`python -m pip install engulf-clab-license-pool`, or through
`engulf-clab-all-plugins`.

## Contents

- [YAML and invocation inputs](#yaml-and-invocation-inputs)
- [Allocation and cleanup](#allocation-and-cleanup)
- [Selection strategies](#selection-strategies)
- [Pool and identity rules](#pool-and-identity-rules)
- [Generated files and topology mutation](#generated-files-and-topology-mutation)
- [MCP and security](#mcp-and-security)
- [Troubleshooting](#troubleshooting)

## YAML and invocation inputs

Set a node's Containerlab `license` field to `$POOL_NAME`. Set the invocation
environment variable with that exact name to a directory of license files.

```yaml
topology:
  nodes:
    router:
      image: vrnetlab/vr-router:latest
      uuid: 4c1a8ee8-6ef7-4501-bfc1-6b082c3120f0
      license: $ROUTER_LICENSES
      env:
        ECLAB_LIC_CLAMP: serial-0001.lic
```

```bash
export ROUTER_LICENSES=$PWD/licenses/router
eclab deploy -t lab.clab.yml
```

| YAML / environment item | Meaning |
| --- | --- |
| `license: $POOL_NAME` | Select from the directory named by `$POOL_NAME` in the invocation environment. |
| `uuid` | Recommended stable node identity. Without it, the node name is used. |
| `env.ECLAB_LIC_CLAMP` | Optional required filename or path within the pool. Deploy fails if it is allocated. |
| `POOL_NAME=/path/to/licenses` | Invocation environment variable; value must be a directory. |
| `--eclab-license-pool-strategy STRATEGY` | Select `sticky`, `round-robin`, or `least-recently-used` for this invocation. |
| `ECLAB_LICENSE_POOL_STRATEGY` | Persistent strategy default; `sticky` when unset. |
| `--eclab-license VALUE` | Global non-interactive file, pool, or `$VARIABLE` for a frozen-license prompt. |

The CLI strategy takes precedence over `ECLAB_LICENSE_POOL_STRATEGY`:

```bash
eclab deploy -t lab.clab.yml \
  --eclab-license-pool-strategy least-recently-used
```

`ECLAB` is a fixed label prefix, the same across every edition. It controls
frozen shared labs too: freeze writes `license: __ECLAB_LICENSE_PROMPT__`, and
deploy accepts `ECLAB_LICENSE` or `ECLAB_LICENSE_<NODE_NAME>` for
non-interactive use. `ECLAB_LICENSE` is the supported persistent global
default, while `--eclab-license VALUE` overrides it for one invocation and
`ECLAB_LICENSE_<NODE_NAME>` remains the per-node override. Otherwise the plugin
asks for a license file, pool directory, or `$VARIABLE`. A directory is
allocated using the same shared pool mechanism; a file is copied only into the
running lab's generated topology.

## Allocation and cleanup

Allocations are globally coordinated in user state and guarded by leases, so
multiple labs can share a pool. The selected strategy chooses among currently
free licenses; an active valid claim is reused under every strategy so a failed
deployment can be retried safely. Clamped licenses are considered last for
ordinary allocation. The selected file is copied under
`.<state-prefix-lowercase>/licenses/` beside the topology and the generated
topology references that copy. This state-directory prefix is derived from the
active application's short product name — unlike the fixed `ECLAB` label prefix
above. Branding-only editions may keep `eclab` and share
`.eclab/licenses/`; a superset executable with its own schema pipeline uses its
pipeline ID as `short_product_name` and therefore gets a separate copy
directory. Pool allocation coordination remains per canonical pool.

A successful `destroy` releases that workspace's claims and removes its copied
licenses. `destroy -a` / `destroy --all` releases every recorded allocation.

## Selection strategies

`sticky` is the compatibility default. It preserves the prior selector:
never-used free files first, then a free file historically associated with the
same claim, then other non-clamped free files, and finally any free file.

`round-robin` sorts the pool's canonical file paths and selects from a persisted
next index, wrapping at the end. If that entry is allocated or historically
clamped, the selector scans forward to the next ordinary free entry. Explicit
clamps do not advance the automatic-selection index.

`least-recently-used` records each pool license use with a monotonic pool-local
sequence and chooses the ordinary free file with the oldest sequence. A file
with no recorded use is oldest. Reusing an active claim refreshes its recorded
use. Logical sequence numbers avoid dependence on host clocks or file
timestamps.

Strategy cursors and usage history remain after claims are released so future
deployments can rotate fairly. Switching strategy does not replace an active
claim; complete a successful destroy first when the next deploy should choose a
different free license. An explicit `ECLAB_LIC_CLAMP` always selects its exact
available file regardless of strategy and records that use.

Existing version-1 registries migrate automatically; their historical entries
receive a baseline use sequence while genuinely unseen files remain oldest.

## Pool and identity rules

A pool contains regular files directly inside the selected directory; allocation
does not recurse into subdirectories. The plugin stores canonical absolute pool
and file paths in Engulf user state but never writes them into the source
topology. File contents are copied only to the lab-local generated area.

The allocation claim combines the canonical workspace-state root with the
node's `uuid`, falling back to its topology name. Use a stable globally unique
UUID when a node may be renamed or when multiple labs use similar node names.
Changing the UUID intentionally creates a new allocation identity.

For ordinary allocation, an existing valid claim is reused. Otherwise the
configured strategy selects a free file as described above. A clamp resolves to
one exact pool entry and fails if that file is absent or currently claimed.
Clamp history keeps specially assigned files out of ordinary preference while
other choices remain.

All pools touched by one deploy are leased together before the short registry
transaction. This prevents two local eclab workspaces from assigning the same
file concurrently. An allocation made before a later deployment failure remains
claimed so retrying the same lab is stable; run a successful destroy to release
it.

## Generated files and topology mutation

Each selected license is copied beneath:

```text
<topology-directory>/.<state-prefix-lowercase>/licenses/<claim-hash>/<source-filename>
```

The shared topology editor changes only the temporary derived topology's
`license` value to that copy. The selected source YAML and original pool file are
unchanged. Successful single-lab destroy releases claims beginning with that
workspace identity and removes the generated license directory. Destroy-all
clears all recorded allocations; use it only when intentionally affecting every
known workspace.

Deploy emits one info-level diagnostic per licensed node with the node name and
selected license basename. It never logs the canonical pool/file path or license
contents. Basenames and node names are escaped in the diagnostic so unusual
filesystem or topology characters cannot inject extra log lines.

Direct frozen-license file choices are copied to the same generated area but do
not allocate a shared pool. Directory choices use normal pool leasing and
history. A `$VARIABLE` choice is resolved once from the invocation environment
before the path is classified.

## MCP and security

License files and pool paths are sensitive privileged inputs. Do not put a host
path or license content in version-controlled topology, README, frozen archive,
caller-visible MCP metadata, or the packaged skill. Use an environment variable
for local CLI operation.

For MCP, every variable named by `license: $POOL` and every frozen-license value
must be configured in the selected root-owned profile. The service rejects
caller overrides so an agent cannot make the root daemon copy an arbitrary host
file. Profile names may be advertised; values and secrets are not.
`ECLAB_LICENSE_POOL_STRATEGY` is also profile-owned because it is an
`ECLAB_LICENSE*` runtime control; set it in the profile's ordinary environment
map when MCP-managed labs should use a non-default strategy.

## Troubleshooting

- If a pool variable is missing, confirm its exact case and value in the same
  CLI environment or MCP profile used for deploy.
- If the pool is empty, ensure regular license files are directly inside it and
  readable by the launcher/service account.
- If all files are allocated, destroy inactive workspaces normally before
  considering any manual state intervention.
- If a strategy value is rejected, use exactly `sticky`, `round-robin`, or
  `least-recently-used`; values are lowercase and hyphenated.
- If changing strategy appears to keep the old license, the workspace still has
  an active claim. Complete a successful destroy before redeploying when
  rotation is intended.
- If a clamp is unavailable, confirm the exact filename, that it is a top-level
  pool entry, and that another workspace does not own it.
- If a frozen deploy cannot prompt, set the node-specific value before the
  `--eclab-license` global value. Node names are uppercased and non-alphanumeric
  characters become underscores.
- Do not edit the registry or remove generated copies while a lab is active.
  Preserve state and use targeted diagnostics to identify the owning workspace.

## Runtime schema discovery

The plugin records its topology properties, node variables, runtime variables,
and this packaged README during `before_goal`; the generator runs only after all
active contributors have recorded their controls.
