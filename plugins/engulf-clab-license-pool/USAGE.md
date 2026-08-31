# engulf-clab-license-pool

Allocates license files from a shared directory pool and points only the
temporary deploy topology at a lab-local copy.

Install with `python -m pip install engulf-clab-license-pool`, or through
`engulf-clab-all-plugins`.

## Inputs

Set a node's `license` to `$POOL_NAME`, then set that invocation environment
variable to a directory containing license files directly at its top level:

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
eclab deploy -t lab.clab.yml \
  --eclab-license-pool-strategy least-recently-used
```

| Input | Meaning |
| --- | --- |
| `license: $POOL_NAME` | Allocate from the directory named by that invocation variable. |
| `uuid` | Recommended stable node identity; node name is the fallback. |
| `env.ECLAB_LIC_CLAMP` | Require one exact pool filename/path; fails when absent or claimed. |
| `--eclab-license-pool-strategy` | Per-invocation `sticky`, `round-robin`, or `least-recently-used`. |
| `ECLAB_LICENSE_POOL_STRATEGY` | Persistent strategy default; `least-recently-used` when unset. |
| `--eclab-license VALUE` | Global file, pool, or `$VARIABLE` for a frozen-license prompt. |

The CLI strategy wins over its environment default. One invocation selects one
strategy, but each canonical absolute pool independently owns its cursor and
use history; path aliases to the same pool share allocation state. `ECLAB` is a
fixed prefix across editions.

## Selection strategies

| Strategy | Automatic selection | Persistent history |
| --- | --- | --- |
| `sticky` | Never-used free file, prior file for this claim, another non-clamped free file, then any free file. | Prior claim associations. |
| `round-robin` | Sort canonical pool files and scan from the saved next index, wrapping past claimed or historically clamped entries. | Next automatic index. |
| `least-recently-used` | Default: choose the ordinary free file with the oldest pool-local use sequence; unseen files are oldest. | Monotonic use sequence per file. |

All strategies first reuse a valid active claim so retries remain stable. An
explicit clamp selects its exact available file regardless of strategy and is
recorded as clamped; it does not advance round-robin's automatic index.
Ordinary selection avoids clamped history while another choice exists.

Strategy history remains after release. Changing strategy therefore does not
replace an active claim: successfully destroy the lab before redeploying when a
different license is intended. Reusing an active claim refreshes LRU use.
Version-1 registries migrate automatically: historical entries receive a
baseline use sequence while genuinely unseen files remain oldest.

## Allocation lifecycle

A pool contains only regular files directly inside its directory; allocation
does not recurse. The claim combines the canonical workspace identity with the
node UUID, or node name when no UUID is present. Use a stable globally unique
UUID when nodes may be renamed or different labs use similar names. Changing
the UUID intentionally creates a new allocation identity.

All pools touched by one deploy are coordinated together so concurrent local
workspaces cannot claim the same file. The selected source is copied beneath:

```text
<topology-directory>/.<state-prefix-lowercase>/licenses/<claim-hash>/<filename>
```

Only the temporary topology receives that copy's path. The source YAML, pool
file, and license contents are unchanged. Pool/file identities are retained in
user state, but license contents are not. A failed, preempted, interrupted, or
cancelled deploy rolls back the claims and lab copies first created by that
invocation. A retry that reused an existing claim does not release that claim
when it fails.

A successful `destroy` releases that workspace and removes its generated
copies. `destroy -a` or `destroy --all` clears every recorded allocation but
does not traverse other workspace directories to remove their generated copies.
Do not edit allocation state or delete generated copies while a lab is active;
preserve state and use targeted diagnostics to identify the owning workspace.

The lab-local state prefix is the normalized callback-bound short product name,
with product metadata as fallback. Editions sharing that short name share the
copy directory; different names separate it. Branding-only editions may keep
`eclab` and share `.eclab/licenses/`, while a superset executable with its own
schema pipeline uses its pipeline ID as `short_product_name` and therefore gets
a separate copy directory. Canonical pool allocation remains shared. Deploy
logs one selected basename per licensed node, never the pool path, generated
path, or contents. Basenames and node names are escaped in that diagnostic so
unusual filesystem or topology characters cannot inject extra log lines.
Logical use sequence numbers avoid any dependence on host clocks or file
timestamps.

## Frozen prompts and security

Freeze replaces every node `license` value with `__ECLAB_LICENSE_PROMPT__`,
including direct file licenses that never used a pool. Deploy then resolves
`ECLAB_LICENSE_<NODE_NAME>`, `--eclab-license VALUE`, and the `ECLAB_LICENSE`
persistent default in that order, otherwise prompting for a file, directory
pool, or `$VARIABLE`. A `$VARIABLE` answer is resolved once from the invocation
environment before the resulting path is classified. Direct files are copied
without a pool claim; directories use normal allocation and history.

License files and paths are sensitive privileged inputs. Keep them out of
version-controlled topologies, documentation, archives, the packaged skill, and
caller-visible MCP metadata. Profile names may be advertised; values and
secrets are not. Under MCP, pool variables and frozen-license values are
profile-owned secrets, and `ECLAB_LICENSE_POOL_STRATEGY` is profile-owned too —
set it in the profile's ordinary environment map. Caller overrides are rejected
so an agent cannot make the root daemon copy an arbitrary host file. Use an
environment variable for local CLI operation.

## Troubleshooting

- Confirm a pool variable's exact case and its value in the same CLI
  environment or MCP profile actually used for deploy.
- Confirm regular license files are directly inside the pool directory and
  readable by the launcher or service account; under MCP the reader is the root
  daemon, not the caller.
- If all files are claimed, successfully destroy inactive workspaces before
  considering state intervention.
- Use exactly `sticky`, `round-robin`, or `least-recently-used`; values are
  lowercase and hyphenated.
- If a strategy change keeps the same file, release the active claim first.
- For clamp failures, verify the exact top-level filename and whether another
  workspace owns it.
- For noninteractive frozen deploys, set the node-specific value before the
  global value; node names are uppercased with non-alphanumeric runs replaced
  by underscores.
