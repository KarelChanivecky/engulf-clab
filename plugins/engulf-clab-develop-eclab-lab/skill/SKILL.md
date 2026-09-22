---
name: @@SKILL_NAME@@
description: Build, refine, validate, operate, and troubleshoot Containerlab labs with @@SHORT_PRODUCT@@ and its exact active Engulf plugins. Use for topology authoring, minimal reproductions, managed plugin controls, lifecycle operations, or runtime failures.
---

# Develop labs with @@SHORT_PRODUCT@@

## Load the installed runtime

1. Derive `<CONFIG_ROOT>` from this installed file: it is the parent of the
   `skills/` directory containing the skill.
2. Run `@@SHORT_PRODUCT@@ @@INSTALL_COMMAND@@ <CONFIG_ROOT>` to refresh the
   eclab runtime inventory. If it fails, do not treat an older bundle as proof
   of current availability. If `references/current.json` points to a missing
   or incomplete runtime, this refresh is required; do not fall back to another
   fingerprinted runtime.
3. After refresh, re-read the installed `SKILL.md` and `references/current.json`.
   Confirm the executable and schema pipeline in the active catalog, using
   runtime help as the command authority.
4. Route through the catalog. Read only the relevant provider's compact
   `schema.yaml`, then open a routed reference when detailed syntax, lifecycle,
   security, or troubleshooting information is needed. For a specialized
   `kind:`, use the generated node-kind index and that kind's small record.
5. Use `references/current.json` or `catalog.json` for programmatic paths and
   fingerprint checks. Use the full topology schema for validation, not feature
   discovery.

Direct Containerlab does not run wrapper plugins. For service-managed labs, use
the service's discovery and job lifecycle because its workspace, privileges,
and environment may differ from the local shell.

## Author the lab

- Containerlab YAML is the base language. Add only controls advertised by the
  active provider schemas.
- Inspect existing lab instructions, topology, and referenced startup files
  before changing them.
- Keep reproductions to the interfaces, routes, objects, policies, users, and
  services on the failing path while preserving object dependencies.
- Follow the selected node-kind, image, startup, licensing, and helper contracts
  from their providers. Do not infer vendor behavior from the generic skill.
- Never assign, rename, or use `eth0` as a topology or data-plane link endpoint;
  Containerlab reserves it for node management.
- Use environment variables for supported persistent defaults and CLI flags for
  per-invocation overrides; flags win when the provider advertises both.
- Keep addressing, routing, policy, credentials, and secrets in the lab-owned
  inputs rather than generic helper images or committed runtime output.
- Do not embed credentials, license contents, personal paths, private
  repositories, or service secrets.
- Treat plugin-produced topology files as temporary derived output and preserve
  the source topology.

## Validate and operate safely

- Validate the raw source topology with the generated full schema. Also check
  relationships JSON Schema cannot prove, such as endpoint uniqueness, address
  overlap, and helper interface contracts.
- Honor provider `requires`, `conflicts_with`, `implies`, path-base, lifecycle,
  privilege, host-tool, and ordering metadata. Runtime analyzers remain
  authoritative for conditional cross-field rules.
- Prefer read-only help and diagnostics for discovery. Do not test availability
  by deploying, destroying, building images, or altering host networking.
- Deploy, destroy, remove runtime output, alter host networking, or clean state
  only when the user authorizes that operation.
- Identify the exact lab and its owned resources before cleanup. Use the
  narrowest supported recovery operation when normal cleanup is blocked.
- Poll asynchronous operations to a terminal result.
- Use an advertised freeze or export capability for sanitized sharing. Do not
  assume external files, credentials, or license contents are embedded.

## Diagnose in layers

1. Confirm the topology, workspace, lifecycle interface, executable, selected
   pipeline, and active plugin inventory.
2. Locate the first failing layer: base schema, plugin analysis, preparation or
   host work, Containerlab, cleanup, or a privileged service.
3. Open the responsible provider's schema and references. For missing node
   interfaces, first check whether every endpoint container or virtual appliance
   started successfully before changing link definitions.
4. Correct the first invalid or missing dependency, rerun the narrowest safe
   validation, and preserve the evidence needed to reproduce the failure.

The exact installed-runtime catalog follows. Its paths are relative to this
skill and lead to fingerprinted schemas and references.
