# Plugin Instructions

This plugin produces a shareable archive without ever changing the source lab.
Never place license files, license pool paths, allocations, or clamps in a frozen
artifact. Keep the archive build staged and atomic so a failed freeze cannot leave
a partial output at its requested destination.

- Keep `freeze` as a before-goal control command that preempts Containerlab.
  Acquire the workspace freeze lease; offline mode also leases the managed
  Containerlab and vrnetlab repositories.
- Preserve source immutability, deterministic topology selection, explicit
  output suffix validation, overwrite confirmation, external-symlink rejection,
  Git-ignore-style exclusions, empty-directory pruning, and tracked archive
  exclusion.
- Redact every node license, remove every `*_LIC_CLAMP`, exclude likely license
  files, and fail when generated lab-local license copies exist.
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
- Keep README archive layout, exclusion, launcher, offline, and license behavior
  synchronized with implementation and tests.
- Run command, plugin, and state tests. Mock pip, Docker, Git, and tool lookup;
  use temporary labs and never deploy during automated validation. Build and
  inspect a wheel, then regenerate freeze skill references.
