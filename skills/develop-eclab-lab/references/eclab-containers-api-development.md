# Container Collections API Instructions

Keep this package declarative, typed, and independent of the Engulf runtime.
Public contract changes require a major-version review. Do not add filesystem
discovery or topology mutation here.

- Import only `engulf_api` and `engulf_executable_wrapper_api`; never import
  `engulf` or the container manager implementation.
- Keep public dataclasses frozen and validate/copy mutable caller inputs into
  immutable tuples or mapping proxies during construction.
- Preserve the plugin ID, context ID, manager dependency, namespace
  normalization, and before-goal registration contract.
- Keep filesystem existence and Docker/topology work in the manager. The API may
  require absolute package asset paths but must not inspect or build them.
- Update `__all__`, type markers, README field tables/examples, and contract
  tests together when changing public surface.
- Run this package's tests plus manager and core-collection tests after any API
  change. Build and install a wheel to verify package typing and entry-point
  consumers against installed artifacts.
- Regenerate the skill's API and development references for every contract or
  documentation change.
