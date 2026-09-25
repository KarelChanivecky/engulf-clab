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
- Use the fixed `ECLAB` prefix (`command._LABEL_PREFIX`) for the portable
  license marker, rewritten vrnetlab input key, and freeze lease name — never
  derive these from application metadata; the freeze lease in particular must
  stay fixed so two differently-branded editions freezing the same workspace
  concurrently actually block each other. The workspace state directory and
  ignore-file name are the one thing that stays derived from callback-bound
  short product metadata (`command._state_prefix`); keep this split
  intentional rather than reusing one prefix for both.
- Format 3 records every installed package name and version without URLs or
  paths, plus the mode, producer edition, and tool identities. Select the
  runtime provider by producer edition through the API entry-point group and
  fail explicitly when absent; never import an edition's implementation from
  the shared package.
- The launcher filename and every launcher's exec target derive from the
  producer edition (`command._launcher_name`); do not hardcode
  `run-eclab.sh`. Keep lean, runtime, and offline launchers distinct: lean
  runs the installed edition without a compatibility prompt, runtime mode
  enforces pinned tools, and offline execution may use only bundled
  runtime/tools and the host Docker daemon — never PATH or a package index.
- Keep package locking transitive and prefer verified locally installed wheels
  before package-index download. Missing runtime-mode wheels may warn with an
  index fallback; incomplete offline runtime/tool/image inputs must fail.
- Never archive generated vrnetlab appliance images or vendor VM inputs in
  offline mode. Preserve entitled recipient selection and local rebuild.
- Write the archive to a staged path and publish only after all work succeeds.
  Track it in workspace state without nesting previous outputs.
- Keep README archive layout, exclusion, launcher, offline, and license behavior
  synchronized with implementation and tests.
- Run command, defrost, plugin, state, and runtime tests. Mock pip, Docker,
  Git, and tool lookup; use temporary labs and never deploy during automated
  validation. Build and inspect a wheel, then regenerate freeze skill
  references.