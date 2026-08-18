---
name: engulf-clab-develop-eclab-lab
description: Build, refine, validate, operate, and troubleshoot Containerlab labs with eclab. Use for eclab topologies, minimal repro extraction, vrnetlab image inputs, license pools, managed WAN bridges, packaged helper containers, freeze workflows, MCP lifecycle operations, or Engulf-backed lab failures. Do not use as a general Engulf plugin-development tutorial.
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
7. Available plugins print on --help after the containerlab help.
8. If engulf-clab-containers is installed you can inspect the available containers with --eclab-containers-help

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
That choice changes which topology controls exist; topology labels and
environment keys keep the fixed `ECLAB` prefix under every edition.

Choose one topology runtime:

| Runtime | Meaning | Recognition and consequences |
| --- | --- | --- |
| Direct Containerlab | Run the topology without Engulf or eclab plugins. | Documentation uses `containerlab deploy/destroy`. Do not add eclab-managed WAN labels, license-pool variables, freeze behavior, or other plugin controls. |
| Base eclab | Run Containerlab through the standard `engulf-clab` application and its declared plugins. | Documentation uses `eclab`; dynamic help lists installed plugin features. The label prefix is `ECLAB`. |
| eclab edition | Run through an organization- or product-specific launcher that reuses `engulf-clab`. | The launcher has its own display/short product metadata and may select another plugin catalog. Topology labels and environment keys still use the fixed `ECLAB` prefix. |

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
- Short product name: eclab
- Label prefix: ECLAB (fixed)
- Lifecycle: MCP profile `default`
```

Omit inapplicable fields for direct Containerlab. Never record credentials,
license paths, or profile-owned secrets. On later work, treat this block as the
workspace preference unless the user explicitly changes it.

For eclab, topology labels and environment-variable keys use a fixed `ECLAB_*`
prefix, the same across every edition — never derive it from application
metadata, dynamic help, or the executable filename. For managed WANs use
`ECLAB_DHCP_*` labels and `ECLAB_UPLINK_IF`; do not mix in a similarly named
prefix that belongs to a separate, unrelated tool.

A different, unrelated prefix governs only the topology-local state directory
that plugins like `engulf-clab-freeze` and `engulf-clab-license-pool` write
beside a lab (`.eclab/...`). That one still derives from the active
application's nonempty `short_product_name` (falling back to `product`),
normalized the same way. Editions are expected to keep `short_product_name`
at `eclab` so this state converges on one shared directory; do not confuse it
with the fixed label prefix above.

## Build the smallest useful lab

1. Reduce bug reports and appliance configs to the interfaces, routes, objects,
   policies, users, and profiles on the reproduction path. Preserve dependency
   order and add referenced objects before consumers.
2. Follow the selected node kind's current Containerlab and image contracts;
   do not assume vendor-specific startup, licensing, or management behavior.
3. Use eclab license pools and stable node UUIDs. Never bake a personal license
   path or license content into a lab or skill asset.
4. Choose how each node reaches the WAN/internet. Four patterns exist, in
   order of preference:
   1. Direct through each node's own management `eth0`. Every Containerlab
      node already has outbound reachability through its own `eth0` via
      Docker NAT to the host. Use this when the test does not care which
      path a node's default route takes, nodes reference each other
      directly by IP, or a node (e.g. a server) simply needs its own
      outbound internet access. No extra WAN node, route, or plugin is
      needed.
   2. Non-DHCP explicit route through the packaged
      `eclab.containers/wan-access` node. It forwards and NATs its single
      lab-facing interface through management `eth0`; configure static
      addresses on both sides and point the client's default route at the
      container's data-plane address. Leave every `ECLAB_DHCP_*` variable
      unset.
   3. DHCP explicit route through the specialized
      `eclab.containers/wan-access` node. Same image and forwarding path as
      the non-DHCP pattern, but setting any supported `ECLAB_DHCP_*`
      variable enables its DHCP server and default DHCP configuration.
      Point other nodes' data-plane interfaces at it and configure them for
      DHCP instead of a static route. Read
      [eclab-container-wan-access.md](references/eclab-container-wan-access.md)
      for the environment contract and interface requirements.
   4. Host-managed WAN via the `engulf-clab-wan` plugin (`ECLAB_DHCP_WAN`
      bridge). Discouraged: it requires host root and changes host
      networking, and exists only for labs that must not use any node's
      management interface at all — for example exercising a device's own
      DHCP client behavior on a real data-plane WAN port as part of the
      scenario under test. Prefer one of the first three patterns whenever
      the scenario allows using `eth0`. Read
      [eclab-wan.md](references/eclab-wan.md) for the bridge labels,
      lifecycle, and cleanup contract.

   Do not add bare static routes onto a WAN bridge unless the scenario
   specifically requires it.
5. Prefer packaged `eclab.containers/*` nodes over copied Dockerfiles. Read
   [eclab-containers-core.md](references/eclab-containers-core.md) for the
   active catalog, including the `host-connector` VIP-mapping contract and
   the `wan-access` NAT/optional-DHCP contract used by WAN patterns 2 and 3.
   Declare the recipe's required `kind` explicitly in the source topology
   (normally `kind: linux`). Recipe injection and the temporary topology writer
   run only for deploy; destroy, graph, and direct Containerlab calls must still
   be able to parse the unmodified file.
6. Keep lab-specific addressing, routes, credentials, and security policy in
   the consuming lab. Add servers or security features only when the repro
   requires them.
7. Never target a node's `eth0` as a topology `links:` endpoint; it is
   Containerlab's reserved management interface, not a data-plane port to
   wire other nodes into. This has previously caused a built lab to
   accidentally connect a node's data traffic through its own management
   interface. The one exception is a node routing its own traffic out
   through its own `eth0` (see the WAN-access patterns above) — that
   configures the node's default route, it does not wire another node's
   interface to `eth0`.

## Wire shared segments deliberately

Containerlab links are point-to-point, and each `<node>:<interface>` endpoint
may appear only once. For three or more endpoints on one L2 segment, give every
participant a distinct port and connect them through a bridge node. A plain
`kind: bridge` refers to an already existing host bridge; it does not create
one. To create the bridge inside a declared container's network namespace, use:

```yaml
topology:
  nodes:
    segment|parent:
      kind: bridge
      network-mode: container:parent
```

Keep the suffix after `|` exactly equal to the parent node's short topology
name. Containerlab strips the suffix when naming the in-namespace bridge, so
inspect it with `docker exec <parent-container> ip link show master segment`.
Choose a parent that tolerates the bridge and all slave interfaces appearing in
its namespace. Never parent such a bridge on `eclab.containers/wan-access`: its
runtime requires exactly `eth0` plus one lab-facing interface. Prefer a
dedicated inert Linux parent; do not assume an appliance is safe without first
confirming its interface-mapping behavior.

## Validate and operate safely

- After any topology rewiring, parse and validate the raw source file before
  deploy. Use `yaml.safe_load` in a read-only checker rather than inspecting
  only the deploy-time rendered topology. In addition to schema checks, verify
  that every endpoint names a declared node (including the complete
  `segment|parent` bridge name), no endpoint string appears twice, each
  `wan-access` node has exactly one lab link, every plain bridge is an
  intentional pre-existing host bridge, managed recipe nodes declare their
  kind, and every built image uses a literal tag without `${...}` or other
  variable syntax.
- Prefer `eclab_validate` from the configured MCP service for offline graph
  validation. Read [eclab-mcp.md](references/eclab-mcp.md) before MCP work.
- Use MCP job tools for privileged deploy/destroy when configured; otherwise
  use the edition's eclab CLI. Poll asynchronous jobs to a terminal result.
- Do not deploy, destroy, remove runtime output, alter host networking, or clean
  Engulf state unless the user explicitly requests that operation.
- If topology parsing prevents destroy after a deployment exists, do not edit
  the topology and blindly retry a topology-based destroy. Inspect the exact lab
  name and resources, then prefer the selected local launcher’s name-only
  `destroy --name <lab-name>`. If manual cleanup remains necessary, obtain
  authorization, select containers by the exact `containerlab=<lab-name>` label,
  identify the associated management network from inspection, remove only
  those verified targets, and confirm that both lists are empty before deploy.
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
5. For shared-bridge failures, distinguish a `container based bridge requires
   container name as suffix` mismatch from `bridge ... referenced in topology
   but does not exist`, which means a plain bridge expected an existing host
   bridge.
6. For image failures, distinguish packaged containers, Dockerfile builds,
   vrnetlab source discovery, VM input selection, and registry access.
7. For appliance imports, find the first missing or out-of-context object and
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
