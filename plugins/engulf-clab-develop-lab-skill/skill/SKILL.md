---
name: @@SKILL_NAME@@
description: Build, refine, validate, operate, and troubleshoot Containerlab labs with @@SHORT_PRODUCT@@ and its exact active Engulf plugins. Use for topology authoring, minimal reproductions, managed plugin controls, lifecycle operations, or runtime failures.
---

# Develop labs with @@SHORT_PRODUCT@@

## Load the installed runtime

1. Derive `<CONFIG_ROOT>` from this installed file: it is the parent of the
   `skills/` directory containing the skill.
2. Run `@@SHORT_PRODUCT@@ @@INSTALL_COMMAND@@ <CONFIG_ROOT>` to refresh the
   installed runtime inventory. If it fails, do not treat an older bundle as
   proof of current availability.
3. Route through the catalog appended below. Read only the relevant provider's
   compact `schema.yaml`, then open a routed reference when detailed syntax,
   lifecycle, security, or troubleshooting information is needed.
   When the topology uses a specialized `kind:`, open the generated node-kind
   index, then that kind's small YAML record and only its available
   Containerlab or vrnetlab reference.
4. Use `references/current.json` or the catalog JSON for programmatic paths and
   fingerprint checks. Use the full topology schema for validation, not feature
   discovery.

Direct Containerlab does not run wrapper plugins. For MCP-managed labs, use the
service's discovery and job lifecycle because its workspace, privileges, and
environment may differ from the local shell.

## Author the lab

- Containerlab YAML is the base language. Add only controls advertised by the
  active provider schemas.
- Inspect the existing lab instructions, topology, and referenced startup
  configurations before changing them.
- Keep reproductions to the interfaces, routes, objects, policies, users, and
  services on the failing path, preserving object dependencies.
- Follow the selected node kind, image, and helper contracts. Keep addressing,
  routing, policy, and credentials in the lab rather than generic helpers.
- Never assign, rename, or use `eth0` as a topology or data-plane link
  endpoint. Containerlab reserves it for the node's management interface — as
  do virtual appliances for their first port (FortiGate `port1`).
- Runtime environment variables are prefixed with the edition's short product
  name (`@@SHORT_PRODUCT@@`, uppercased); the active runtime's help and
  provider schemas show the exact form.
- Use environment variables for persistent defaults and CLI flags for
  per-invocation overrides; flags win.
- Ensure every deployed container provides basic network diagnostics: `ping`,
  `traceroute`, DNS lookup (`nslookup` or equivalent), `nc`, `tcpdump`, or the
  platform's corresponding commands.
- Do not embed credentials, license contents, personal paths, private
  repositories, or service secrets.
- Treat plugin-produced topology files as temporary derived output; preserve
  the source topology.

### Virtual-appliance kinds

Kinds such as `fortinet_fortigate` run a VM under vrnetlab, not a container:

- Boot from a versioned startup config named by the node's `startup-config:`
  and enforce it, so each deploy starts from that config rather than stale
  runtime state.
- Build disk images with the runtime's vrnetlab pipeline; never commit the
  resulting images to source control.
- Draw licenses from the license-pool plugin and keep node identities stable.
- Give the lab a data-plane default route through a managed DHCP-WAN bridge on
  the appliance's first data interface (in DHCP mode), which installs the
  default route from the lease.

## Choose WAN access deliberately

Use the least invasive method that exercises the behavior the lab needs:

1. Rely on the automatic management network and container-runtime NAT when the
   test does not care about a data-plane default route. Do not author `eth0`
   into the topology; no WAN node is needed.
2. Use a packaged WAN-access node with static data-plane addressing when the
   client must route through a WAN node without DHCP.
3. Enable DHCP on the packaged WAN-access node when the test needs an explicit
   DHCP-served data-plane WAN.
4. Use a host-managed bridge WAN only when the test must exercise a real
   data-plane DHCP client or cannot use management networking. It changes host
   networking, requires elevated privileges, and needs reliable cleanup.

Read the chosen provider schema before authoring its controls. Packaged-node
environment variables and host-managed bridge labels belong to different
plugins and lifecycles.

For shared segments, verify endpoint cardinality, bridge ownership, parent
naming, and helper interface constraints in the selected provider references.

## Capture and health

Where provider schemas advertise them:

- Gate deploys on appliance readiness (a `--<product>-wait-healthy` flag)
  before driving a fresh lab programmatically or reporting a repro result.
- Capture a node's live, re-deployable config (for example `get-config`),
  which merges redacted or secret-placeholder fields back from the startup
  config.

## Validate and operate safely

- Validate the raw source topology with the generated full schema. Also check
  topology-wide relationships that JSON Schema cannot prove, such as endpoint
  uniqueness and helper interface contracts.
- Use provider `requires`, `conflicts_with`, `implies`, path base, lifecycle,
  privilege, host-tool, and ordering metadata. Runtime analyzers remain
  authoritative for conditional cross-field rules.
- Prefer read-only help and diagnostics for discovery. Do not test availability
  by deploying, destroying, building images, or altering host networking.
- Deploy, destroy, remove runtime output, alter host networking, or clean state
  only when the user authorizes that operation.
- If a broken topology prevents cleanup, identify the exact lab and its owned
  resources before using a narrower supported operation.
- Poll asynchronous MCP operations to a terminal result.
- Use the runtime's freeze capability for sanitized sharing. Do not assume
  external files, credentials, or license contents are automatically embedded.

## Troubleshooting

1. When expected `eth*` interfaces disappear from one or more nodes, check
   every container attached to those links: one that failed to start can cause
   Containerlab to drop or never create the peer interfaces on otherwise
   running nodes. Fix the first failed container and redeploy before changing
   link or interface configuration.

## Diagnose in layers

1. Confirm the topology, workspace, lifecycle interface, executable, and active
   plugin inventory.
2. Locate the failing layer: base schema, plugin analysis, preparation or host
   work, Containerlab, cleanup, or privileged service.
3. Use the responsible provider's schema and references to trace networking,
   bridge, image, licensing, or configuration-import failures.
4. Correct the first invalid or missing dependency instead of expanding the lab.

The exact installed-runtime catalog follows. Its paths are relative to this
skill and lead to fingerprinted schemas and references.
