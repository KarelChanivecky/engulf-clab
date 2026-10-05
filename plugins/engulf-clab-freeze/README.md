# engulf-clab-freeze

Portable lab archive creation, expansion, and recipient workflows.

Default freeze records compatibility without bundled runtime or captured image
snapshots. Authored files named by `ECLAB_IMAGE_ARCHIVE` remain part of the lab
source copy when they are in scope and survive the freeze exclusions.
`--eclab-with-runtime` writes an executable `.run` package containing
`runtime/`, `lab.tgz`, `defrost.sh`, and a short `README.md` guide. Running the
package automatically builds the pinned venv from its bundled wheelhouse when
needed and defrosts the lab, including environment initialization and recipient
license prompts. If no license pool is registered, defrost offers to create a
pool directory and initialize it through the edition's `init-license-pool`
command. Freeze installs the license-pool plugin and orders it before defrost's
pool check, which reads the registry from the owning plugin's state namespace.
The pool starts empty, so add entitled license files before using
automatic allocation. Afterward, defrost points to the restored lab's
`FREEZE-README.md` for run instructions. The restored lab is written to
`./<package-name>`; pass an output directory as the first argument, such as
`./package.run restored`, or use `--eclab-output DIRECTORY` after the package
name to choose another output directory.
Defrost attaches the runtime to the restored lab. `--eclab-offline` also writes
a self-extracting `.run` package with the active Python environment and required
images, and running it automatically defrosts the lab too.
Offline freezing includes images for plugin-generated service nodes. The frozen
topology selects `images.freeze.json`, and the active image-archive provider
loads its snapshots during deploy or redeploy.

If a defrosted runtime lab reports that Containerlab requires root privileges,
run `./run-eclab.sh sudoless` from the expanded lab as your normal user, then
log out and back in before deploying. Repeat after rebuilding `.eclab-venv`.

New archives use format 3 and optional feature packages extend staging through
`engulf-clab-freeze-api`; defrost also accepts legacy format 1 and 2 archives.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
