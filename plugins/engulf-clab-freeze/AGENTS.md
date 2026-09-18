# Plugin Instructions

This plugin produces a shareable archive without ever changing the source lab,
and expands one back into a runnable lab. Never place license files, license pool
paths, allocations, or clamps in a frozen artifact; only the expanded lab holds a
recipient's real selections. Keep both the archive build and the expansion staged
and atomic so a failure cannot leave a partial output at its requested destination.

- Derive from `SchemaBackedPlugin` so the command, scoped flags, and paths come
  from `PLUGIN_SCHEMA`. Thread the immutable invocation environment through
  provenance, source resolution, and offline bundling so normalized wrapper
  options survive before-goal preemption.
- Declare the schema ordering edge only in
  `engulf.plugins.v1.dependency.engulf_clab_freeze` package metadata. Do not
  restore `plugin_dependencies` on the class; Engulf rejects code-declared
  dependencies.
- Keep `freeze` and `defrost` as before-goal control commands that preempt
  Containerlab. Freeze acquires the workspace freeze lease; offline mode also
  leases the managed Containerlab and vrnetlab repositories. Defrost acquires
  only a lease on its destination, computed by `defrost.lease` without argparse
  side effects, and reads no workspace state.
- Keep defrost the exact reverse of freeze and never a general archive
  extractor. Require the `x-engulf-clab-freeze` metadata and its supported
  format, remove that key from the restored topology, reject members escaping
  the single archive root, and stage the expansion beside the destination so a
  failure leaves no partial lab and restores a replaced one.
- Format 2 discovers optional hooks only through `engulf-clab-freeze-api` entry
  points. Contributors may claim namespaced flags, transform the staged copy,
  add metadata, and restore inside unpublished staging; freeze must never import
  an optional feature package. Defrost accepts formats 1 and 2.
- Replace a destination only when it carries this plugin's defrost record. The
  record keeps the removed freeze provenance beside the lab, never inside it.
- Resolve licenses from `--license`, then `ECLAB_LICENSE_<NODE_NAME>`, then
  `ECLAB_LICENSE`, then an interactive prompt, and leave an unanswered marker
  for deploy. Never log, record, or embed a license value in an error message;
  name only the node, exactly as license-pool does.
- Select a bundled image archive only when it carries the node's exact image
  reference and the node declares none, because `ECLAB_IMAGE_ARCHIVE` suppresses
  the registry fallback. Selection must not need Docker; only `--load-images`
  may use it.
- Prepare runtimes after publication so recorded absolute paths are the final
  ones, and validate offline runtime completeness before it. Offline
  incompleteness fails; a normal-mode installation failure warns, removes its
  partial environment, and defers to `run-eclab.sh`.
- Preserve source immutability, deterministic topology selection, explicit
  output suffix validation, overwrite confirmation, external-symlink rejection,
  Git-ignore-style exclusions, empty-directory pruning, and tracked archive
  exclusion.
- Treat `.engulf-clab-lab-*.clab.yml` and `.engulf-clab-lab-*.clab.yaml` as
  deploy-time writer output. Exclude it from new archives and remove it while
  defrosting legacy archives so a portable lab has one authored topology.
- Redact every node license, remove every `*_LIC_CLAMP`, exclude likely license
  files, and fail when generated lab-local license copies exist.
- Sanitize every declaration origin, including shadowed and unused kinds/groups.
  Resolve defrost image/archive selections and license prompts with EffectiveNode.
- Generate `initialize-env.sh` from the final frozen topology's environment
  references. It is recipient-run, writes only non-empty answers to the
  topology's expected sibling `.env` file with mode `0600`, and never carries
  source values into the archive; defrost restores its executable bit and runs
  it before recipient resolution unless `--skip-env-init` is selected. The
  format-2 metadata marker gates execution so unmarked legacy files are never
  treated as generated helpers.
- Freeze's offline image and vrnetlab-input paths use the same EffectiveNode
  snapshots, while sanitizing generated input paths at every declaration origin.
- Use the fixed `ECLAB` prefix (`command._LABEL_PREFIX`) for the portable
  license marker, rewritten vrnetlab input key, defrost's per-node license
  variables and `ECLAB_IMAGE_ARCHIVE` key, and both lease names — never derive
  these from application metadata. It must match license-pool's
  `LicenseContract` label prefix and ensure-vrnetlab's and image-archive's
  `LABEL_PREFIX` exactly, because these commands write labels those plugins
  later read back; the leases in particular must stay fixed so two
  differently-branded editions freezing the same workspace or expanding into one
  destination concurrently actually block each other. The workspace state directory and
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
- Both commands perform all work in `before_goal` and have no `prepare_call`
  phase, so executable-wrapper `prepare_failed` cleanup does not apply here.
  Before either command preempts the goal, acknowledge the Containerlab and
  vrnetlab schema-source contexts because the terminal schema consumer will not
  run; ordinary non-freeze invocations must leave those contexts untouched.
- Keep `USAGE.md` archive layout, exclusion, launcher, offline, expansion, and
  license behavior synchronized with implementation and tests.
- Run command, defrost, plugin, and state tests. Mock pip, Docker, Git, and
  tool lookup; use temporary labs and archives, and never deploy or load images
  during automated validation. Record the
  schema before handling either command, and run `make check-skill`.
