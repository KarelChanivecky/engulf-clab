# Plugin Instructions

Contributor contexts carry that contributor's own Engulf state namespace, not
the freeze plugin's callback-bound directory. Keep namespace resolution in the
freeze orchestrator; PKI must receive its existing global catalog and issued
material. Do not create contributor state while discovering it. The opt-in
[`freeze-roundtrip` suite](../../tests/integration/freeze-roundtrip/README.md)
exercises this boundary with real deployments; it is separate from unit validation.

This plugin produces a shareable archive without ever changing the source lab,
and expands one back into a runnable lab. Never place license files, license pool
paths, allocations, or clamps in a frozen artifact; only the expanded lab holds a
recipient's real selections. Keep both the archive build and the expansion staged
and atomic so a failure cannot leave a partial output at its requested destination.

- Derive from `SchemaBackedPlugin` so the command, scoped flags, and paths come
  from `PLUGIN_SCHEMA`. Thread the immutable invocation environment through
  provenance, source resolution, and offline bundling so normalized wrapper
  options survive before-goal preemption.
- Freeze writes an archive and defrost writes a lab directory through their
  respective `--eclab-output` flags. The schema allows one annotation per flag
  name, so annotate that shared name once for both commands; keep defrost's
  destination lease parser aligned with its argparse option.
- `--eclab-with-runtime` writes a self-extracting `.run` package with
  `runtime/`, `lab.tgz`, and `defrost.sh`; keep runtime files out of the inner
  archive. Offline packages are self-extracting `.run` files too. Running the
  package extracts to a temporary directory and invokes `defrost.sh`, which
  builds the bundled venv from its wheelhouse when needed and runs normal
  defrost. The defrost path owns `initialize-env.sh`, license prompts, runtime attachment,
  and the non-blocking dependency report. The restored launcher blocks only
  operations whose declared host tools or libraries are missing.
- Keep license-pool discovery on the public `engulf-clab-license-pool-lib`
  manager. When a defrosted topology has redacted license prompts but no pool
  is registered, offer the edition's `init-license-pool` command and preserve
  the caller's working directory for relative pool paths. Direct `auto` answers
  still require a registered pool; never describe the marker as an assigned
  license.
- Resolve host requirements from callback-collected `RuntimeRequirement` records.
  Use the schema API's command, topology-feature, and `unless_artifacts`
  conditions; do not duplicate plugin dependency declarations in freeze code.
  Tests cover Containerlab binaries and vrnetlab images supplied in the package.
- Declare schema, Docker image-build, and vrnetlab-build ordering edges only in
  `engulf.plugins.v1.dependency.engulf_clab_freeze` package metadata. Run the
  two provenance hydrations before this plugin so Docker image provider and
  vrnetlab source records are present when a control command preempts
  Containerlab. Do not restore `plugin_dependencies` on the class; Engulf
  rejects code-declared dependencies.
- Keep `freeze` and `defrost` as before-goal control commands that preempt
  Containerlab. Freeze acquires the workspace freeze lease; offline mode also
  leases the managed Containerlab and vrnetlab repositories. Defrost acquires
  only a lease on its destination, computed by `defrost.lease` without argparse
  side effects. Image-build and vrnetlab-build separately hydrate their saved
  provenance before either control command runs; defrost reads no freeze state.
- Keep defrost the exact reverse of freeze and never a general archive
  extractor. Read `freeze.json` beside the topology for new archives, accept
  legacy `x-engulf-clab-freeze` metadata, reject members escaping the single
  archive root, and stage the expansion beside the destination so a failure
  leaves no partial lab and restores a replaced one.
- Replace a destination only when it carries this plugin's defrost record. The
  record keeps the removed freeze provenance beside the lab, never inside it.
- Resolve licenses from `--eclab-license`, then `ECLAB_LICENSE_<NODE_NAME>`, then
  `ECLAB_LICENSE`, then `--eclab-auto-license`, then an interactive prompt;
  accept `auto` as a registered-pool request and leave an unanswered marker
  for deploy. Never log, record, or embed a license value in an error message;
  name only the node, exactly as license-pool does.
- Select a bundled image archive only when it carries the node's exact image
  reference and the node declares none, because `ECLAB_IMAGE_ARCHIVE` suppresses
  the registry fallback. Freeze and defrost must not load images; the image
  archive provider loads them during deploy or redeploy.
- Treat image-source declarations with a node absent from authored topology as
  generated image roots. Their offline archives must be captured even though
  the plugin will recreate those nodes only during deploy preparation. Keep the
  image-manifest selector in the frozen topology so the image-archive provider
  can activate for the generated nodes.
- Prepare runtime mode after publication so recorded absolute paths are final;
  validate offline completeness before publication. Runtime mode must fail
  rather than run mismatched tools. Lean mode checks compatibility once at
  defrost and persists the warnings.
- Preserve source immutability, deterministic topology selection, explicit
  output suffix validation, overwrite confirmation, external-symlink rejection,
  Git-ignore-style exclusions, empty-directory pruning, and tracked archive
  exclusion.
- Resolve the optional freeze `LAB_DIR` through the parser's single-topology
  discovery, defaulting to the invocation directory. Keep `-t` and
  `--eclab-topology` as exclusive explicit-file selectors; scope all freeze
  control flags with `--eclab-` and align argparse, schema, help, and usage.
- Name the default archive after the selected lab directory and publish it in
  the invocation directory. Resolve explicit `--eclab-output` there as well.
- Redact every node license, remove every `*_LIC_CLAMP`, exclude likely license
  files, and fail when generated lab-local license copies exist.
- Generate `initialize-env.sh` only from the final staged topology, after
  contributor and offline rewrites. Keep variable discovery aligned with the
  parser's `$NAME` and `${NAME...}` syntax, accept exported values for
  noninteractive initialization, and test shell quoting, empty
  answers, mode `0600`, defrost execution in staging, and
  `--eclab-skip-env-init` suppression.
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
- Format 3 records all installed package names and versions without URLs or paths
  in `freeze.json`, outside the Containerlab topology.
  Record the producing edition's transitive runtime package names separately for
  lean compatibility checks; development tools remain provenance only. Older
  format 3 archives fall back to the recipient runtime closure plus archived
  Engulf and edition packages. Keep the version lock and wheelhouse exclusive to
  runtime and offline modes. The producing edition selects a runtime provider through
  `engulf_clab.freeze.runtime.v1`; no provider means an explicit error.
- Offline bundling removes the producer-specific `command` from `pyvenv.cfg`
  and converts Python console scripts to shell wrappers backed by
  `.eclab-frozen-scripts/`. Preserve `sys.argv[0]` and the original bin path on
  `sys.path`; the launcher uses the new edition wrapper when present and keeps
  its old direct-Python path for previously frozen archives.
- Keep lean, runtime, and offline launchers distinct. Lean uses the installed
  edition without a compatibility prompt. `_freeze_readme()` renders the packaged
  `readmes/<mode>.md` guide into every archive as `FREEZE-README.md` with
  `string.Template` placeholders `$topology`, `$edition`, `$launcher`, and
  `$licenses` (a generated license-pool section, empty for unlicensed labs);
  write a literal dollar sign as `$$`, and update a guide whenever its mode's
  recipient behavior changes. Runtime mode assumes only Python
  on the recipient. `_download_wheels()` seeds the wheelhouse from installed
  artifacts (copied local wheels, editable projects built from source, other
  pure packages repacked from their installed files) and downloads only the
  rest with `--no-deps`, so an index copy never replaces the producer's build.
  `_download_python_wheels()` adds compiled wheels per CPython minor and writes
  `python-versions.freeze.txt`. The recipient builds `.eclab-venv` with
  `--no-index`, and `prepare_recipient()` installs the Containerlab executable
  and vrnetlab tree bundled under `tools/` (vrnetlab's revision is recorded in
  `.eclab-freeze-revision`) into it; never clone, fetch, or rebuild them.
  Offline execution uses only bundled runtime/tools and host Docker.
- The lab-writer's hidden `.engulf-clab-lab-*` topology is derived deploy output,
  not portable source. Freeze must omit it, and defrost must remove it from
  legacy archives before publication.
- Use the common image acquisition planner in every mode. Lean and runtime modes
  keep literal Dockerfile dependencies and packaged provider recipes; use
  recipient variables only for unavailable root images or actual missing recipe
  inputs. They emit no captured image archives; a declared, in-scope image
  archive that survives exclusions remains an authored source input. Lean mode
  must reject a missing lab-local archive instead of replacing its path with a
  recipient variable. Offline accepts only bundled artifacts or declared offline
  builds. Do not reintroduce blanket vrnetlab or image-name exclusions.
- Preserve an authored single-variable source expression in lean mode, including
  an empty default such as `${FCLAB_DEMO_IMAGE:-}`. The initializer must prompt
  for the authored variable name rather than a generated `ECLAB_FREEZE_*` name.
- Discover recipe facts from packaged static Dockerfile image providers and the
  freeze image-source entry-point group, never by running deploy preparation.
  Providers with host-local recipe inputs must declare them through the freeze
  API. Capture Docker images by immutable ID and keep image identity, checksums,
  platform, dependencies, and decisions in the manifest. Put shared manifest
  inputs on one topology node; do not copy them into every node environment.
- New defrost uses the explicit image manifest and validates it before
  publication. Keep incidental archive scanning only for legacy archives.
  The archive provider must supply dependency-only images as well as roots.
- Preserve every source file. Rewrite only staging; disable captured builds
  at every inherited origin and preserve actual recipient input variables in
  lean mode.
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

## Validation

Sanitize through the parser's complete declaration-origin inventory, including
unused and shadowed kind/group entries. Use EffectiveNode for defrost image
selection and inherited license prompts; flatten recipient license answers to
node values for license-pool's per-node prompt contract.

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-freeze/src
.venv/bin/python -m pytest -q plugins/engulf-clab-freeze/tests
.venv/bin/python -m pytest -q plugins/engulf-clab-freeze/tests/test_runtime.py plugins/engulf-clab-freeze/tests/test_defrost.py
make check-skill
```

Freeze reads labels written by `engulf-clab-license-pool` and
`engulf-clab-ensure-vrnetlab`, and defrost writes keys read by those plugins and
by `engulf-clab-image-archive`; run their suites after a label-prefix change.

Run `make build-<package>` for a distribution build (or `make build` for
every distribution), and `git diff --check` before committing. Never run
real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
