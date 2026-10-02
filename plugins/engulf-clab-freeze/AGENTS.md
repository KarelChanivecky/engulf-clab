# Plugin Instructions

- Pass each contributor its own sibling Engulf user/workspace namespace.
  Callback-bound `api.state()` belongs to freeze; passing it directly prevents
  PKI export and automatic authority binding from finding existing identities.
  Keep runtime-provider state handling separate from contributor contexts.

This plugin produces a shareable archive without ever changing the source lab,
and expands one back into a runnable lab. Never place license files, license pool
paths, allocations, or clamps in a frozen artifact; only the expanded lab holds a
recipient's real selections. Keep both the archive build and the expansion staged
and atomic so a failure cannot leave a partial output at its requested destination.

- Derive from `SchemaBackedPlugin` so the command, scoped flags, and paths come
  from `PLUGIN_SCHEMA`. Thread the immutable invocation environment through
  provenance, source resolution, and offline bundling so normalized wrapper
  options survive before-goal preemption.
- Freeze and defrost both use `--eclab-output`; keep one shared schema annotation
  for that flag, with command-specific parser meanings and destination leases.
- `--eclab-with-runtime` writes a self-extracting `.run` package with
  `runtime/`, `lab.tgz`, and `defrost.sh`; offline packages are `.run` files as
  well. Running either package automatically executes `defrost.sh`; keep
  runtime artifacts out of the inner lab archive. The script builds the venv
  from the wheelhouse when needed and runs normal defrost.
  The generated self-extractor accepts a leading positional output directory
  and `--eclab-output DIRECTORY` before forwarding defrost options.
  Defrost attaches the runtime before publication, then runs the regular env
  initializer and license resolution. `--eclab-no-runtime` skips attaching the
  venv so the lab launcher builds it later.
- Resolve `RuntimeRequirement` records from the schema registry passed by the
  plugin callback. Keep applicability in the schema API (`commands`, topology
  features, and `unless_artifacts`); suppress Go when a Containerlab binary is
  bundled and QEMU tools when the opted-in vrnetlab images are bundled. Keep
  host-library checks shell-only so extraction never needs Python.
- Declare schema, Docker image-build, and vrnetlab-build ordering edges only in
  `engulf.plugins.v1.dependency.engulf_clab_freeze` package metadata. Run
  both provenance hydrations before this plugin so Docker image provider and
  vrnetlab source records are restored before freeze or defrost preempts the
  normal goal. Do not restore `plugin_dependencies` on the class; Engulf rejects
  code-declared dependencies.
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
- Formats 2 and 3 discover optional hooks only through `engulf-clab-freeze-api` entry
  points. Contributors may claim namespaced flags, transform the staged copy,
  add metadata, and restore inside unpublished staging; freeze must never import
  an optional feature package. Defrost accepts formats 1, 2, and 3.
- Replace a destination only when it carries this plugin's defrost record. The
  record keeps the removed freeze provenance beside the lab, never inside it.
- Resolve licenses from `--eclab-license`, then `ECLAB_LICENSE_<NODE_NAME>`, then
  `ECLAB_LICENSE`, then `--eclab-auto-license`, then an interactive prompt;
  accept `auto` as a registered-pool request and leave an unanswered marker
  for deploy. Never log, record, or embed a license value in an error message;
  name only the node, exactly as license-pool does.
- On defrost, query registered pools through `engulf-clab-license-pool-lib`.
  If frozen license prompts exist and no pool is registered, offer the existing
  edition `init-license-pool` workflow before asking for per-node sources.
  Keep relative pool paths anchored to the caller's directory even though a
  self-extractor runs defrost from its temporary staging directory. After
  publication, point the recipient at the lab's `FREEZE-README.md`.
- Select a bundled image archive only when it carries the node's exact image
  reference and the node declares none, because `ECLAB_IMAGE_ARCHIVE` suppresses
  the registry fallback. Freeze and defrost must not load images; the image
  archive provider loads them during deploy or redeploy.
- Include plugin-generated image roots from freeze image-source declarations.
  A dynamic node absent from the authored topology still needs an image decision
  and immutable archive in offline mode. Keep their archive paths in the image
  manifest selected by `ECLAB_IMAGE_ARCHIVE_MANIFEST`, so the image-archive
  provider can provision them after the plugin creates the nodes.
- Prepare runtime mode after publication so recorded absolute paths are final;
  validate offline completeness before publication. Runtime mode must fail
  rather than run mismatched tools. Lean mode checks compatibility once at
  defrost and persists the warnings.
- Preserve source immutability, deterministic topology selection, explicit
  output suffix validation, overwrite confirmation, external-symlink rejection,
  Git-ignore-style exclusions, empty-directory pruning, and tracked archive
  exclusion.
- Resolve optional freeze `LAB_DIR` through single-topology discovery, default
  to the invocation directory, and reject using it with explicit `-t` or
  `--eclab-topology`. Keep freeze control flags scoped with `--eclab-`.
- Put the default archive in the invocation directory, named after the selected
  lab directory; explicit `--eclab-output` still resolves from that directory.
- Treat `.engulf-clab-lab-*.clab.yml` and `.engulf-clab-lab-*.clab.yaml` as
  deploy-time writer output. Exclude it from new archives and remove it while
  defrosting legacy archives so a portable lab has one authored topology.
- Redact every node license, remove every `*_LIC_CLAMP`, exclude likely license
  files, and fail when generated lab-local license copies exist.
- Sanitize every declaration origin, including shadowed and unused kinds/groups.
  Resolve defrost image/archive selections and license prompts with EffectiveNode.
- Generate `initialize-env.sh` from the final frozen topology's environment
  references. It is recipient-run, writes only non-empty answers to the
  topology's expected sibling `.env` file with mode `0600`, accepts exported
  values for noninteractive use, and never carries source values into the archive;
  defrost restores its executable bit and runs
  it before recipient resolution unless `--eclab-skip-env-init` is selected. The
  format-2 metadata marker gates execution so unmarked legacy files are never
  treated as generated helpers.
- All image planning uses EffectiveNode snapshots, while sanitizing owned
  acquisition controls at every declaration origin.
- Lean image planning preserves an authored single-variable source expression,
  including `${NAME:-}`, so the recipient initializer asks for the authored name.
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
  Record runtime package names separately for lean compatibility; never report
  unrelated producer development tools as missing on the recipient. For older
  archives, compare the recipient runtime closure plus archived Engulf and edition
  packages. Keep the version lock and wheelhouse for runtime and offline modes.
  Select a runtime provider by producer edition through the API entry
  point and fail explicitly when absent.
- Offline bundling must remove `pyvenv.cfg`'s producer-specific creation command
  and rewrite Python console scripts as wrappers around `.eclab-venv/bin/python`.
  Keep their original `sys.argv[0]` and script-directory import path; the offline
  launcher must use the wrapper for new archives and retain its Python fallback
  for older archives.
- Keep lean, runtime, and offline launchers distinct. Lean uses the installed
  edition without a compatibility prompt. Each mode owns one packaged recipient
  guide in `src/engulf_clab_freeze/readmes/<mode>.md`, rendered into the
  archive as `FREEZE-README.md`; change it with the mode's behavior. The
  `$licenses` section is rendered only for nodes whose effective license is the
  prompt marker, and lists only node names and kinds, never values or pool
  paths. Runtime
  mode assumes only Python on the recipient: it bundles a complete wheelhouse for every supported CPython
  minor plus the producer's Containerlab executable and vrnetlab working tree,
  and the recipient builds `.eclab-venv` with `pip install --no-index` and
  installs both tools into it. Never clone, fetch, or rebuild tools for a
  runtime archive, and never let an index copy replace an installed package:
  the producer's state may exist nowhere else. Offline execution uses only
  bundled runtime/tools and host Docker.
- Frozen runtime launchers must clear checkout version controls: a version
  value requests a Git update even when the update switch is off. Verify the
  bundled revisions from archive metadata instead.
- Bundle vrnetlab without its Git history, then write an invalid `.git` boundary
  file in the copy so Git cannot traverse into the recipient lab repository.
  The revision marker remains the bundled tree's source of identity.
- Use the common image acquisition planner in every mode. Lean and runtime modes
  keep literal Dockerfile dependencies and packaged provider recipes; use
  recipient variables only for unavailable root images or actual missing recipe
  inputs. They emit no captured image archives; a declared, in-scope image
  archive that survives exclusions remains an authored source input. Reject a
  missing lab-local image archive in lean mode rather than silently replacing
  its path with a recipient variable. Offline accepts only bundled artifacts or
  declared offline builds.
  Do not reintroduce blanket vrnetlab or image-name exclusions.
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
- Run `test_runtime.py` and `test_defrost.py` after changing the runtime bundle
  wrapper, runtime attachment, or recipient setup. Their shell and archive
  cases cover venv preparation before defrost and normal license and
  environment initialization.
