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
- Preserve safe qcow2 staging, tag restoration, state fingerprinting, leases,
  per-builder serialization, and invocation-map cleanup.
- Keep reads of `ECLAB_VRNETLAB_TYPE` internal to selecting the vrnetlab
  builder directory; user-facing syntax remains declared by providers.
- Do not declare source flags, environment aliases, node controls, completion,
  or freeze source discovery here. Those contracts belong to providers.
