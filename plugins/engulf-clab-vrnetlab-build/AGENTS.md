# Plugin Instructions

This distribution is the single vrnetlab image builder and Docker image
provider adapter. It consumes source paths from
`engulf-clab-vrnetlab-build-api` and build-node metadata from the shared
topology session.

- Do not declare source CLI flags, provider environment variables, or custom
  source-selection YAML in this package. Keep those controls in providers.
- Keep its plugin ID `engulf_clab.vrnetlab_build` and Docker provider ID
  `org.engulf.docker.vrnetlab-build` stable.
- Run after the parser and all source providers, and before image resolution
  and the lab writer. Declare ordering in packaging metadata.
- Use API-resolved exact-node paths before the `default` path.
- Require all requests that fall back to the API `default` path to share one
  `ECLAB_VRNETLAB_TYPE`; exact-node source paths may use distinct types.
- Preserve safe qcow2 staging, requested-tag restoration, Docker's own build
  cache behavior, leases, per-builder serialization, and invocation-map cleanup.
- Invoke the selected vrnetlab Makefile for every source-backed topology
  mutation. Do not persist build fingerprints or skip Make based on source or
  checkout fingerprints; Docker decides whether its build cache can be reused.
- Before removing an old image's temporary backup tag, check for running
  containers based on it. If any exist, preserve the new requested tag, retain
  the backup, and warn with its name and the containers. If cleanup still fails,
  preserve the new tag and include Docker's error detail in a warning. Do not
  roll back a successful build only because backup cleanup is blocked.
- Carry source-provider IDs and staged qcow2 fingerprints into the separate
  `VRNETLAB_SOURCE_PROVENANCE_CONTEXT`, keyed by topology node; never put source
  attribution into Docker image provider provenance.
- Log each source-backed node's requested image, resolved source path, source
  provider ID, and Docker image provider ID through callback-bound logging;
  never persist the local path.
- Hydrate this registry on every call and persist successful deploy/redeploy
  snapshots in workspace state without local source paths. Publish through the
  API helper so the context remains optional when no consumer is installed.
- Keep reads of `ECLAB_VRNETLAB_TYPE` internal to selecting the vrnetlab
  builder directory; user-facing syntax remains declared by providers.
- Do not declare source flags, environment aliases, node controls, completion,
  or freeze source discovery here. Those contracts belong to providers.
