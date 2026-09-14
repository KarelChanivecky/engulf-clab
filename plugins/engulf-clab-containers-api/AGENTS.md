# Container Collections API Instructions

Keep this package declarative, typed, and independent of the Engulf runtime.
Public contract changes require a major-version review. Do not add filesystem
discovery or topology mutation here.

- Import only `engulf_api`, `engulf_executable_wrapper_api`, and the neutral
  `engulf_docker_image_api`; never import `engulf` or the container manager.
- Keep public dataclasses frozen and validate/copy mutable caller inputs into
  immutable tuples or mapping proxies during construction.
- Preserve the plugin ID, context ID, manager dependency, namespace
  normalization, and before-goal registration contract.
- Do not declare `plugin_dependencies` on `ContainerCollectionPlugin` or any
  subclass. Engulf rejects code-declared dependencies, and a base-class
  attribute would fail every collection that inherits it. Each collection
  distribution declares its own ordering edge on
  `CONTAINER_MANAGER_PLUGIN_ID` in its
  `engulf.plugins.v1.dependency.<plugin_id>` entry-point group.
- Keep filesystem existence and topology work in the manager and Docker work in
  the neutral image core. The API may require absolute package asset paths but
  must not inspect or build them.
- Update `__all__`, type markers, README field tables/examples, and contract
  tests together when changing public surface.
- Run this package's tests plus manager and core-collection tests after any API
  change. Build and install a wheel to verify package typing and entry-point
  consumers against installed artifacts.
- Regenerate the skill's API and development references for every contract or
  documentation change.
