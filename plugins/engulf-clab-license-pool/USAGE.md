# engulf-clab-license-pool

Allocates license files from a shared directory pool and points only the
temporary deployment topology at a lab-local copy. This runs for deploy and
single-source redeploy.

Install with `python -m pip install engulf-clab-license-pool`, or through
`engulf-clab-all-plugins`.

## Registered pools and automatic allocation

Register an existing pool directory for one Containerlab node kind:

```bash
eclab init-license-pool [PATH] [--kind KIND]
```

`PATH` defaults to the invocation directory and `KIND` defaults to
`fortinet_fortigate`. The command stores the canonical directory and kind in
ordered user state; it does not copy, inspect, or log license contents.
Re-registering the same path updates its kind in place. There may be multiple
pools for a kind. An active claim remains stable; a new claim scans matching
pools in registration order and uses the first one with an available license.
The plugin consumes the first positional argument as `PATH` and its own
`--kind` option. It ignores additional options and positional arguments so
other plugins can extend the command without this plugin rejecting their
inputs. A missing or invalid value for the plugin-owned `--kind` still fails.
Containerlab itself is preempted only after every active plugin's `before_goal`
and `analyze_call` callbacks have received the command, allowing other plugins
to extend it. Wrapper preemption skips `prepare_call` because no external call
will be attempted.

Set `license: ECLAB_AUTO_LICENSE` to request registered-pool allocation
explicitly. An unresolved variable such as `license: $FORTIGATE_LICENSES` also
falls back to registered pools when the variable is absent. Set effective node
environment `ECLAB_DISABLE_AUTO_LICENSE: "true"` to disable only this implicit
unresolved-variable fallback; the explicit marker still requests automatic
allocation. Relative and absolute license paths retain their normal file or
directory meaning and never trigger this fallback.

Automatic allocation requires the node's effective `kind` to match the
registration exactly. The kind may be inherited through Containerlab defaults,
kind, group, or node scope. Using a registered directory explicitly also checks
that match, preventing a product-specific pool from being applied to the wrong
node kind. A request fails before Containerlab starts when no matching pool is
registered or every matching pool is out of licenses.

At deploy-time discovery, registrations whose directories no longer exist are
removed from user state. Restore and re-register a moved pool before retrying.

## Inputs

Set a node's `license` to `$POOL_NAME`, then set that invocation environment
variable to a directory containing license files directly at its top level.
Only regular, non-empty files whose names do not begin with `.` are
candidates: dotfiles and zero-byte placeholders are skipped, so editor
swapfiles, `.DS_Store`, and sync metadata cannot be claimed and served as
licenses. A dotfile is skipped by its name in the pool, even when it is a
symlink to a real license; name the target instead. Clamping to a skipped
entry fails as unavailable rather than selecting it.
Any `license` naming a directory is a pool, so a literal path and the
`${POOL_NAME:-/default}` forms Containerlab expands during parsing work the
same way; a `license` naming a regular file stays Containerlab's own:
an unset, `null`, or empty-string `license` is also left unhandled by this
plugin.

The `license`, `FOS_UUID`, and `ECLAB_LIC_CLAMP` values inherit through
Containerlab's `defaults < kind < group < node` scopes. Put a shared selector
on a kind or group when every matching node should use it; a node-level value
overrides the inherited value.

```yaml
topology:
  nodes:
    router:
      image: vrnetlab/vr-router:latest
      license: $ROUTER_LICENSES
      env:
        FOS_UUID: 4c1a8ee8-6ef7-4501-bfc1-6b082c3120f0
        ECLAB_LIC_CLAMP: serial-0001.lic
```

```bash
export ROUTER_LICENSES=$PWD/licenses/router
eclab deploy -t lab.clab.yml \
  --eclab-license-pool-strategy least-recently-used
```

| Input | Meaning |
| --- | --- |
| `eclab init-license-pool [PATH] [--kind KIND]` | Register or update an ordered automatic pool. |
| `license: ECLAB_AUTO_LICENSE` | Allocate from the first registered matching-kind pool with capacity. |
| `license: $POOL_NAME` | Allocate from the directory named by that invocation variable. |
| `license: <directory>` | Allocate from that directory, however the path was written. |
| `env.FOS_UUID` | Recommended stable node identity; node name is the fallback. |
| `env.ECLAB_LIC_CLAMP` | Require one exact pool filename/path; fails when absent or claimed. |
| `env.ECLAB_DISABLE_AUTO_LICENSE` | When true, do not use registered pools for an unresolved variable. |
| `--eclab-license-pool-strategy` | Per-invocation `sticky`, `round-robin`, or `least-recently-used`. |
| `ECLAB_LICENSE_POOL_STRATEGY` | Persistent strategy default; `least-recently-used` when unset. |
| `--eclab-license VALUE` | Global file, pool, or `$VARIABLE` for a frozen-license prompt. |
| `--eclab-auto-license` | Resolve every unresolved frozen-license prompt from registered matching-kind pools. |

The CLI strategy wins over its environment default. One invocation selects one
strategy, but each canonical absolute pool independently owns its cursor and
use history; path aliases to the same pool share allocation state. `ECLAB` is a
fixed prefix across editions.

## Selection strategies

| Strategy | Automatic selection | Persistent history |
| --- | --- | --- |
| `sticky` | Prior file for this claim, a never-used free file, another non-clamped free file, then any free file. | Prior claim associations. |
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

All pools touched by one deployment are coordinated together so concurrent local
workspaces cannot claim the same file. The selected source is copied beneath:

```text
<topology-directory>/.<state-prefix-lowercase>/licenses/<claim-hash>/<filename>
```

Only the temporary topology receives that copy's path. The source YAML, pool
file, and license contents are unchanged. Pool/file identities and ordered
registered-pool paths and kinds are retained in user state, but license contents
are not. A failed, preempted, interrupted, or
cancelled deploy or redeploy rolls back the claims and lab copies first created by that
invocation. If this plugin completes preparation but a later plugin fails
preparation, the preparation unwind performs the same rollback before
Containerlab starts. A failure inside license preparation rolls back its own
partial work immediately. A retry that reused an existing claim does not release
that claim when it fails.

A successful `destroy` releases that workspace and removes its generated
copies. `destroy -a` or `destroy --all` clears every recorded allocation and
removes the generated copies from every workspace the registry recorded a claim
for, reading those workspaces before the allocations are cleared. Only the
plugin's own copy directories are deleted; nothing else in a workspace is
touched.
Do not edit allocation state or delete generated copies while a lab is active;
preserve state and use targeted diagnostics to identify the owning workspace.

The lab-local state prefix is the normalized callback-bound short product name,
with product metadata as fallback. Editions sharing that short name share the
copy directory; different names separate it. Branding-only editions may keep
`eclab` and share `.eclab/licenses/`, while a superset executable with its own
schema pipeline uses its pipeline ID as `short_product_name` and therefore gets
a separate copy directory. Canonical pool allocation remains shared. Deploy
logs one selected basename and pool per licensed node, never the generated
path or license contents. Direct-file selections report `None` as the pool.
Basenames, pool paths, and node names are escaped in that diagnostic so
unusual filesystem or topology characters cannot inject extra log lines.
Logical use sequence numbers avoid any dependence on host clocks or file
timestamps.

## Published selection breadcrumb

After a successful deploy or single-source redeploy preparation, the plugin publishes what each node
actually received on the `engulf_clab.license_pool.selection` context, as a
read-only mapping of node name to `LicenseSelection`. Both the context id and
the dataclass are exported from `engulf_clab_license_pool`:

```python
from engulf_clab_license_pool import LICENSE_SELECTION_CONTEXT, LicenseSelection

selection = api.get_context(LICENSE_SELECTION_CONTEXT) or {}
for node, chosen in selection.items():
    if chosen.from_pool and chosen.source_name.endswith(".example"):
        ...
```

`LicenseSelection` carries `node`, `source_name` (the selected file's
basename), `source_path`, and `pool`, which is the directory a pooled license
came from and `None` when the license was named directly. Branch on
`from_pool` rather than on the path, which is absolute and host-specific.

This exists because neither fact is otherwise recoverable downstream: the
allocation state is plugin-private, and by the time other plugins read the
topology the node's `license` field holds the lab-local copy rather than the
origin. It lets an edition-specific plugin apply rules this one has no opinion
about, such as recognising a particular license suffix. Declare the context in
the reading plugin's `context_reads`.

The plugin reads the context back at the point of publication and logs the
provenance it holds at debug level. Reading marks the context consumed, so an
edition that ships no reader for this extension point does not trip the
framework's warning that a context was written but never read. The debug log
records only the basename and pooled/direct flag; the info-level selection log
additionally records the selected pool. Resolved source and generated-copy
paths stay out of the logs.

An alternate edition allocator may use the shared library registry and publish
`LicenseAllocationHandoff` through
`LICENSE_ALLOCATION_HANDOFF_CONTEXT`. When present for an invocation, this
plugin skips allocation and cleanup. The alternate provider must own leases,
copies, rollback, and destroy cleanup.

## Frozen prompts and security

Freeze replaces every node `license` value with `__ECLAB_LICENSE_PROMPT__`,
including direct file licenses that never used a pool. Deploy then resolves
`ECLAB_LICENSE_<NODE_NAME>`, `--eclab-license VALUE`, and the `ECLAB_LICENSE`
persistent default in that order, otherwise prompting for `auto`, a file,
directory pool, or `$VARIABLE`. `auto` requests allocation from registered
matching-kind pools. A `$VARIABLE` answer is resolved once from the invocation
environment before the resulting path is classified. Direct files are copied
without a pool claim; directories use normal allocation and history.

License files and paths are sensitive privileged inputs. Keep them out of
version-controlled topologies, documentation, archives, the packaged skill, and
caller-visible MCP metadata. Profile names may be advertised; values and
secrets are not. Under MCP, pool variables and frozen-license values are
profile-owned secrets, and `ECLAB_LICENSE_POOL_STRATEGY` is profile-owned too —
set it in the profile's ordinary environment map. Caller overrides are rejected
so an agent cannot make the root daemon copy an arbitrary host file. Use an
environment variable for local CLI operation. `init-license-pool` registers a
path visible to the account running eclab; when a service owns execution, run
the command through that same trusted service context rather than registering a
client-only path.

## Troubleshooting

- Confirm a pool variable's exact case and its value in the same CLI
  environment or MCP profile actually used for deploy.
- Confirm `init-license-pool` used the exact effective node kind shown in the
  topology. Kinds are case-sensitive and missing directories are deregistered.
- If automatic selection reports no available license, inspect matching pools
  in registration order and release inactive claims with normal lab destroy.
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
