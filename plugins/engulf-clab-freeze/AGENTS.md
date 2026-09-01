# Plugin Instructions

This plugin produces a shareable archive without ever changing the source lab.
Never place license files, license pool paths, allocations, or clamps in a frozen
artifact. Keep the archive build staged and atomic so a failed freeze cannot leave
a partial output at its requested destination.

- Derive from `SchemaBackedPlugin` so the command, scoped flags, and paths come
  from `PLUGIN_SCHEMA`. Thread the immutable invocation environment through
  provenance, source resolution, and offline bundling so normalized wrapper
  options survive before-goal preemption.
- Declare the schema ordering edge only in
  `engulf.plugins.v1.dependency.engulf_clab_freeze` package metadata. Do not
  restore `plugin_dependencies` on the class; Engulf 0.2 rejects code-declared
  dependencies.
- Keep `freeze` as a before-goal control command that preempts Containerlab.
  Acquire the workspace freeze lease; offline mode also leases the managed
  Containerlab and vrnetlab repositories.
- Preserve source immutability, deterministic topology selection, explicit
  output suffix validation, overwrite confirmation, external-symlink rejection,
  Git-ignore-style exclusions, empty-directory pruning, and tracked archive
  exclusion.
- Redact every node license, remove every `*_LIC_CLAMP`, exclude likely license
  files, and fail when generated lab-local license copies exist.
- Use the fixed `ECLAB` prefix (`command._LABEL_PREFIX`) for the portable
  license marker, rewritten vrnetlab input key, and freeze lease name — never
  derive these from application metadata. It must match license-pool's
  `LicenseContract` label prefix and ensure-vrnetlab's `LABEL_PREFIX` exactly,
  because freeze writes labels those plugins later read back; the freeze lease in particular must
  stay fixed so two differently-branded editions freezing the same workspace
  concurrently actually block each other. The workspace state directory and
  ignore-file name are the one thing that stays derived from callback-bound
  short product metadata (`command._state_prefix`); keep this split
  intentional rather than reusing one prefix for both.
- Keep package locking transitive and prefer verified locally installed wheels
  before package-index download. Missing normal-mode wheels may warn; incomplete
  offline runtime/tool/image inputs must fail.
- Keep normal and offline launchers distinct. Offline execution may use only
  bundled runtime/tools and the host Docker daemon; never fall back to PATH or a
  package index.
- Never archive generated vrnetlab appliance images or vendor VM inputs in
  offline mode. Preserve entitled recipient selection and local rebuild.
- Write the archive to a staged path and publish only after all work succeeds.
  Track it in workspace state without nesting previous outputs.
- Freeze performs all work in `before_goal` and has no `prepare_call` phase, so
  executable-wrapper `prepare_failed` cleanup does not apply to this plugin.
- Keep `USAGE.md` archive layout, exclusion, launcher, offline, and license behavior
  synchronized with implementation and tests.
- Run command, plugin, and state tests. Mock pip, Docker, Git, and tool lookup;
  use temporary labs and never deploy during automated validation. Record the
  schema before handling `freeze`, and run `make check-skill`.
