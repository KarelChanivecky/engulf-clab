---
name: develop-eclab-lab
description: Build, refine, validate, operate, and troubleshoot Containerlab labs with eclab. Use for eclab topologies, minimal repro extraction, vrnetlab image inputs, license pools, edition-aware managed WAN bridges, packaged helper containers, freeze workflows, MCP lifecycle operations, or Engulf-backed lab failures. Do not use as a general Engulf plugin-development tutorial.
---

# Develop CLAB with eclab

## Ground the task

1. Read the nearest `AGENTS.md`, lab `README.md`, selected `*.clab.yml`, and
   referenced startup configs before proposing changes.
2. Identify the canonical workspace as the selected topology's directory, or
   the current directory when no filesystem topology is selected. Keep that
   identity stable for Engulf state.
3. Treat every topology as Containerlab YAML and check its base structure against
   the upstream schema before applying runtime-specific plugin contracts.
4. Select the lab runtime and lifecycle interface before adding wrapper-specific
   topology fields or commands, then run that runtime's help to discover the
   plugins and controls actually installed.
5. Use runtime help as the authority for installed behavior, then use the
   package's self-contained references for deeper Engulf, wrapper, MCP, and
   plugin context. If a current source checkout is also available, respect its
   `AGENTS.md` and prefer it over the bundled snapshot. Use
   [source-index.md](references/source-index.md) to find the relevant source or
   development-guidance snapshot.
6. Inspect first, then ask only for choices that materially affect the lab,
   such as license source or host access.

## Start from Containerlab YAML

Every lab topology uses Containerlab's YAML syntax. The authoritative base
definition is the upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json),
whose title is `Containerlab topology definition file`. Use it for the topology
shape and standard fields such as `name`, `mgmt`, `topology`, `defaults`,
`kinds`, `nodes`, `links`, node `kind`, `image`, `env`, `labels`,
`startup-config`, and `license`.

eclab does not introduce a competing topology language. It wraps a Containerlab
invocation. Plugins consume conventions expressed through valid Containerlab
fields, contribute invocation arguments or environment, and may write a
temporary derived topology before Containerlab runs. Begin with schema-valid
Containerlab YAML, then add only the conventions advertised by the selected
runtime's installed plugin help. Do not infer an eclab field merely because it
appears in a different edition, repository snapshot, or old lab.

## Select and remember the lab runtime

Containerlab is the underlying topology engine. eclab is an Engulf wrapper that
runs Containerlab while installed plugins analyze the invocation, modify a
temporary topology, prepare shared host resources, and clean up afterward. An
eclab edition is a separately packaged launcher for the same wrapper application
with different product metadata and possibly a different declared plugin set.
That choice changes which topology controls exist and what their prefix is.

Choose one topology runtime:

| Runtime | Meaning | Recognition and consequences |
| --- | --- | --- |
| Direct Containerlab | Run the topology without Engulf or eclab plugins. | Documentation uses `containerlab deploy/destroy`. Do not add eclab-managed WAN labels, license-pool variables, freeze behavior, or other plugin controls. |
| Base eclab | Run Containerlab through the standard `engulf-clab` application and its declared plugins. | Documentation uses `eclab`; dynamic help lists installed plugin features. The standard application prefix is `ECLAB`. |
| eclab edition | Run through an organization- or product-specific launcher that reuses `engulf-clab`. | The launcher has its own display/short product metadata and may select another plugin catalog. Its normalized short product name determines configuration prefixes. |

Choose the lifecycle interface separately. A local CLI runs the selected
launcher in the user's shell and workspace. The eclab MCP service is not another
topology runtime: it invokes its configured launcher for a stable lab ID under a
server-owned profile, and deploy/destroy operations run as asynchronous jobs.
The MCP profile owns privileged defaults, license-pool paths, and secrets.

Use this decision process:

1. Inspect the lab `README.md`, nearest `AGENTS.md`, topology, and documented
   commands. `containerlab ...` indicates direct use; `eclab ...` indicates the
   base wrapper; another launcher name plus edition metadata or dynamic help
   indicates an edition. Existing `*_DHCP_WAN`, `*_VRNETLAB_*`, or similar
   controls are evidence of an eclab plugin contract, but do not identify the
   edition by themselves.
2. After choosing the runtime, run its read-only help before authoring the lab:
   use `containerlab --help` plus relevant command help for direct Containerlab,
   `eclab --help` for base eclab, or `<edition-launcher> --help` for an edition.
   Do not substitute base eclab help for edition help. Engulf renders a separate
   `Plugin: <plugin-id>` help block for each discovered plugin that implements
   help; those blocks are the current runtime's authoritative feature inventory.
   Read every block relevant to the requested lab and follow any secondary help
   it advertises, such as `--eclab-containers-help` for the active packaged
   container catalog. Absence from runtime help means the feature is unavailable
   until the corresponding plugin is installed or declared for that edition.
3. For MCP-managed labs, also use lab/profile listing and read-only service
   diagnostics to identify the service's configured launcher and advertised
   profiles. Ensure the help came from that same launcher/runtime environment;
   local help from a different installation does not prove a server plugin is
   available. Do not probe availability by deploying.
4. If the evidence is inconclusive, ask: "Should this lab run with direct
   Containerlab, base eclab, or a particular eclab edition? Should lifecycle use
   the local CLI or a configured MCP profile?" If the user does not know, explain
   that eclab is required for eclab-managed WANs, license pools, packaged helper
   preparation, and freeze workflows; recommend direct Containerlab only when
   none of those wrapper features are needed.
5. Reuse the answer throughout the conversation. When creating or materially
   updating the lab, add a durable, non-secret record to its `README.md`:

```markdown
## Lab runtime

- Runtime: eclab edition
- Launcher: acme-clab
- Short product name: acme clab
- Configuration prefix: ACME_CLAB
- Lifecycle: MCP profile `default`
```

Omit inapplicable fields for direct Containerlab. Never record credentials,
license paths, or profile-owned secrets. On later work, treat this block as the
workspace preference unless the user explicitly changes it.

For eclab, obtain the active configuration prefix from application metadata or
dynamic help, never from the executable filename. Metadata derives it from
nonempty `short_product_name`, falling back to `product`, then uppercasing,
replacing non-alphanumeric runs with `_`, and trimming surrounding underscores.

The base product yields `ECLAB`; `vendor clab` yields `VENDOR_CLAB`. Follow each
plugin's current contract; for managed WANs use `<PREFIX>_DHCP_*` labels and
`<PREFIX>_UPLINK_IF`. Do not mix keys from different editions.

## Build the smallest useful lab

1. Reduce bug reports and appliance configs to the interfaces, routes, objects,
   policies, users, and profiles on the reproduction path. Preserve dependency
   order and add referenced objects before consumers.
2. Follow the selected node kind's current Containerlab and image contracts;
   do not assume vendor-specific startup, licensing, or management behavior.
3. Use eclab license pools and stable node UUIDs. Never bake a personal license
   path or license content into a lab or skill asset.
4. For a managed DHCP WAN, configure the connected node to obtain its address
   and route through DHCP when that is the intended topology behavior.
5. Prefer packaged `eclab.containers/*` nodes over copied Dockerfiles. Read
   [eclab-containers-core.md](references/eclab-containers-core.md) for the
   active catalog and host-connector contract.
6. Keep lab-specific addressing, routes, credentials, and security policy in
   the consuming lab. Add servers or security features only when the repro
   requires them.

## Validate and operate safely

- Parse YAML and inspect referenced files before invoking lifecycle commands.
- Prefer `eclab_validate` from the configured MCP service for offline graph
  validation. Read [eclab-mcp.md](references/eclab-mcp.md) before MCP work.
- Use MCP job tools for privileged deploy/destroy when configured; otherwise
  use the edition's eclab CLI. Poll asynchronous jobs to a terminal result.
- Do not deploy, destroy, remove runtime output, alter host networking, or clean
  Engulf state unless the user explicitly requests that operation.
- Use `eclab freeze` for sanitized sharing. Read
  [eclab-freeze.md](references/eclab-freeze.md) before changing or debugging a
  freeze workflow.
- Keep shell examples single-line when practical. For multiline commands, use
  fenced `bash` with explicit `\` continuations and no trailing whitespace.

## Diagnose in layers

1. Confirm the selected topology, canonical workspace, active edition metadata,
   installed plugin set, and executable resolution.
2. Separate side-effect-free analysis failures from `prepare_call()` host work,
   wrapped-process failures, and `after_call()` cleanup.
3. Use callback-bound Engulf diagnostics. Never add direct operational prints or
   configure logging in a plugin while diagnosing it.
4. For WAN failures, check the active prefix, DHCP marker, interface mode,
   uplink, lease-installed route, forwarding, and managed-state ownership.
5. For image failures, distinguish packaged containers, Dockerfile builds,
   vrnetlab source discovery, VM input selection, and registry access.
6. For appliance imports, find the first missing or out-of-context object and
   add only the minimal dependency. Read Engulf snapshots only when the failure
   crosses wrapper/plugin lifecycle or state boundaries.

## Route references

- Engulf callbacks, metadata, contexts, state, leases, and diagnostics:
  [engulf-api.md](references/engulf-api.md)
- Engulf applications, editions, discovery, policies, workspaces, and runtime:
  [engulf-runtime.md](references/engulf-runtime.md)
- Executable-wrapper plugin contracts and immutable contributions:
  [executable-wrapper-api.md](references/executable-wrapper-api.md)
- Executable-wrapper goal dispatch and lifecycle:
  [executable-wrapper.md](references/executable-wrapper.md)
- eclab overview and package map: [eclab.md](references/eclab.md)
- eclab checkout setup, validation, documentation, and release workflow when a
  lab failure requires a source change:
  [eclab-contributing.md](references/eclab-contributing.md)
- Complete privileged-service configuration example when reviewing an MCP
  profile or installation:
  [eclab-mcp-config.md](references/eclab-mcp-config.md)
- Exact plugin syntax: search `references/eclab-*.md` by feature or setting.
