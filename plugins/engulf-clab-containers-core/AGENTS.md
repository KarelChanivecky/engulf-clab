# Core Container Collection Instructions

Recipes in this package are declarative `ContainerDefinition` values. Keep all
Docker build inputs inside the typed package and make runtime behavior generic,
environment-driven, and reusable across labs. The fixed collection plugin ID is
`eclab.containers`, which owns its image namespace. Its goal-specific Docker
image adapter uses the distinct plugin ID `eclab.containers.images`; do not
collapse adapters for unrelated goals back onto one ID.

- Declare the collection manager and last-running schema ordering edges only in
  `engulf.plugins.v1.dependency.eclab_containers` package metadata. Do not add
  `plugin_dependencies` to the adapter class; Engulf rejects code-declared
  dependencies. The independent Docker-image adapter has no plugin dependencies.

- Import only stable API packages. Publish the same recipes through the eclab
  collection adapter and the generic Docker-image goal adapter; neither may
  parse topology YAML, mutate files, invoke Docker, or configure host resources.
- Derive every recipe path from installed package resources and keep the
  Dockerfile inside its declared context. Include every Dockerfile `COPY` input
  in wheels and source distributions.
- Keep `eth0` management assumptions, required capabilities, sysctls, default
  environment, and exposed service contracts synchronized between recipe code,
  Dockerfiles, startup scripts, top-level `USAGE.md`, and image-specific `USAGE.md`.
- Keep `wan-access` NAT independent from DHCP: forwarding and masquerade are
  unconditional, while gateway address assignment and `dnsmasq` require at
  least one supported `ECLAB_DHCP_*` variable.
- Make `wan-access` tolerate Containerlab's temporary veth name by retrying
  activation only when the selected interface disappears during the rename.
- Make `host-connector` tolerate Containerlab's veth/sysctl creation race by
  waiting until every required per-interface sysctl exists.
- Keep images generic. Addressing, routes, credentials, seeds, certificates,
  browser policy, proxy parents, and product-specific behavior belong in the
  consuming lab unless a documented safe development default is essential.
- Do not add undeclared mutable host state. Container runtime state must remain
  inside the container or explicitly mounted lab paths.
- When adding a recipe, use a lowercase Docker-safe name, concise catalog
  summary, package-owned assets, an image-specific guide when configuration is
  nontrivial, and manager/plugin tests for discovery and injected requirements.
- Test declaration/catalog behavior without real Docker. Test pure runtime
  parsers and generators separately; use a real build only when explicitly
  authorized and necessary to validate an image change.
- Run core tests plus container API and manager tests, build the wheel, inspect
  packaged assets, and verify installed catalog help. Keep `PLUGIN_SCHEMA` and
  its last-running generator dependency aligned with recipe controls.
