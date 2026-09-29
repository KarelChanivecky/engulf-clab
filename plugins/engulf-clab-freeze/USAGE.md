# Freeze and defrost labs

Install `engulf-clab-freeze` with the producing edition. The eclab edition
provides the first runtime provider. Freeze selects the single recognized
topology in the positional lab directory, which defaults to `.`. Use `-t` to
select a topology file explicitly; it cannot be combined with a positional
directory. Containerlab YAML is
the base language; see the upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
Plugin controls are conventions layered onto valid Containerlab fields.

```bash
eclab freeze                         # current directory
eclab freeze labs/demo --eclab-output share.tar.gz
eclab freeze labs/demo --eclab-with-runtime
eclab freeze labs/demo --eclab-offline --eclab-bundle-image example/router:1
eclab freeze -t labs/demo/lab.clab.yml
eclab defrost share.tar.gz --eclab-output restored
./restored/run-eclab.sh
```

Output defaults to `./<lab-directory-name>.tar.gz` in the invocation directory
and must end in `.tar.gz` or `.tgz`. Freeze stages and publishes atomically. An existing
regular output prompts for overwrite interactively; symlinks are refused. A
workspace lease prevents concurrent freezes. Offline mode also leases managed
tool repositories.

## Modes

| Mode | Python | Containerlab and vrnetlab | Images |
| --- | --- | --- | --- |
| Default lean | Record every installed package name and version; use the producer edition's installed launcher | Record Containerlab JSON version and commit, and vrnetlab Git revision | Keep complete build recipes and literal Dockerfile dependencies; use recipient variables for unavailable root images and actual missing recipe inputs. No captured image archives. |
| `--eclab-with-runtime` | Add a dependency lock and a complete multi-Python wheelhouse; build `.eclab-venv` from it without a package index at defrost or first launch | Bundle the producer's Containerlab executable and vrnetlab working tree and install them into `.eclab-venv`; never fetch or rebuild them | Same image plan as lean; no captured image archives. |
| `--eclab-offline` | Bundle the active eclab virtual environment and require a complete wheelhouse | Bundle the executable and checkout | Bundle required images or use declared offline builds; no network fallback at runtime. |

`--eclab-bundle-image IMAGE` is repeatable and requires `--eclab-offline`.
`--eclab-external-image IMAGE` is repeatable and applies only to non-offline modes;
the recipient supplies that image. The old `--lean` flag is removed. The
shared `--eclab-with-runtime` spelling is kept across editions; the producing
edition selects its provider. A missing provider is an error.

Freeze resolves inherited settings and recursive dependencies from the topology,
packaged Dockerfile image providers, and `engulf_clab.freeze.images.v1` source
declarations. A literal dependency in a Dockerfile stays literal for the
recipient's installed providers or Docker registry to resolve. A nonportable
root image, VM source, or actual missing recipe input in non-offline modes may
become an `${ECLAB_FREEZE_...}` variable; `initialize-env.sh` asks the recipient
for it. When a VM source already uses a single variable such as
`${FCLAB_DEMO_IMAGE:-}`, lean freeze keeps that expression and prompts for its
original name. Offline mode captures Docker images by immutable ID, checksums each
export, writes each captured node image's archive path to `ECLAB_IMAGE_ARCHIVE`
in the frozen topology, and retains builds only when declared offline
rebuildable. The image archive plugin loads those files during deploy; the image
manifest also retains dependency-only images. If the plugin is absent from the
frozen package set, freeze includes `load-images.sh` as a manual Docker loading
fallback. Docker
access is needed for capture or `--eclab-load-images`; offline use still needs host
Docker and any required QEMU/KVM capabilities.

Freeze copies ordinary lab files subject to `.eclab-freezeignore` (or the
edition's state prefix), excludes runtime state and tracked prior archives,
redacts licenses, removes license clamps and likely license files, and omits
private `.env` values. It refuses generated lab-local license copies. It
never changes the source lab, deploys, pulls, or builds images.

A declared `ECLAB_IMAGE_ARCHIVE` is an authored provisioning input. Lean and
runtime freezes keep its relative path and include the tarball when it is inside
the lab directory and survives the freeze exclusions. A missing lab-local tarball
stops lean freeze with an error so the archive cannot silently lose that input.
Generate the declared tarball before freezing the lab. An archive outside the
lab or excluded by `.eclab-freezeignore` becomes a recipient variable instead.
These source tarballs are distinct from Docker image snapshots captured by the
freeze planner.

## Archive and launcher

Format 3 records `mode`, `producer_edition`, all installed package versions,
the producing edition's runtime package names, tool identities, image decisions,
and license prompts in
`x-engulf-clab-freeze`. `packages.freeze.txt` contains package names and
versions only, with no pip URLs, credentials, or local paths.
`images.freeze.json` records image actions and artifact checksums. Lean
archives include no `wheelhouse/`, `requirements.freeze.txt`, `.eclab-venv/`,
`tools/`, or generated image snapshots. Authored in-scope archive inputs remain
part of the ordinary lab source tree. Runtime archives add the lock, wheelhouse, `python-versions.freeze.txt`,
`tools/containerlab/`, and `tools/vrnetlab/`.
Offline archives also include `.eclab-venv/`, `tools/containerlab/`,
`tools/vrnetlab/`, and required image archives. Defrost leaves image loading to
the installed `engulf-clab-image-archive` plugin during deploy. When that
package is absent from the frozen runtime, defrost writes an executable
`load-images.sh` fallback for loading the bundled snapshots into Docker.
Every archive has
`run-eclab.sh`, `initialize-env.sh`, `FREEZE-WARNINGS.txt`, and
`FREEZE-README.md`, a recipient guide for the archive's mode that names the
producing edition, topology, and launcher. When any node carries a license
prompt, the guide adds a Licenses section naming those nodes and their kinds
and showing how to register a pool with `init-license-pool` and answer `auto`;
it never includes license values or pool paths. Freeze replaces any
`FREEZE-README.md` in the source lab with the guide for the new mode.

The lean launcher executes the producer edition already installed on the
recipient. It creates no environment, prompts for no compatibility override,
and exports no frozen tool pins. Defrost compares runtime packages and tools
once, recording actual mismatches in `FREEZE-WARNINGS.txt`; unrelated producer
development tools are retained only as provenance. Runtime launchers build and run the lab's own `.eclab-venv`;
offline launchers use bundled artifacts and host Docker. With no arguments,
the launcher deploys the frozen topology; arguments replace that default.

Freeze reads contributor-owned state, including PKI's workspace identities and
user catalog. Encrypted exports preserve existing exportable identities; ordinary
user-authority restores can bind automatically to the matching user certificate.

## Defrost

```bash
eclab defrost share.tar.gz --eclab-output restored --eclab-license router=/pools/routers
eclab defrost share.tar.gz --eclab-env ROUTER_IMAGE=router:1 --eclab-no-license-prompt
eclab defrost share.tar.gz --eclab-force --eclab-skip-env-init
```

`--eclab-output` defaults to a directory named after the archive. `--eclab-force` replaces
only a directory carrying a prior defrost record. `--eclab-no-runtime` skips runtime
preparation. `--eclab-no-images` skips bundled image selection; `--eclab-load-images`
loads selected archives immediately. `--eclab-skip-env-init` skips the generated
initializer, which otherwise writes only recipient supplied, nonempty values
to the topology's sibling `.env` file with mode `0600`.

License answers resolve from `--eclab-license NODE=VALUE` (or a bare value for all
nodes), `ECLAB_LICENSE_<NODE>`, `ECLAB_LICENSE`, auto license, then an
interactive prompt. Answers may be `auto`, an existing file or pool directory,
or a `$VARIABLE` for deploy. License answers are neither frozen nor written
to the defrost record.

Defrost requires one archive root and a topology with supported metadata. It
rejects escaping members, invalid image checksums, and missing contributors.
Formats 1 and 2 keep their original restore rules. Format 3 selects the
recorded producer edition's provider. Lean defrost compares the package
manifest (extra recipient packages are allowed), Containerlab `version -j`
version and commit, and vrnetlab Git revision. It reports missing or
mismatched values once, appends them to `FREEZE-WARNINGS.txt`, and records them.
`--eclab-force` regenerates warnings from the archive. The launcher does not repeat
lean checks. Normal eclab provisioning of missing tools remains available.

A runtime archive assumes only Python on the recipient. Freeze captures the
producer's installed packages as they are: recorded local wheels are copied,
editable projects are built from their current source, and other pure-Python
installations are repacked from their installed files. Only packages it cannot
supply itself are downloaded, and freeze fails unless the wheelhouse is
complete. It then adds compiled wheels for every CPython minor from 3.12 up to
the producer's own and lists the minors that resolved in
`python-versions.freeze.txt`. Freeze also copies the selected Containerlab
executable to `tools/containerlab/bin/containerlab` and the vrnetlab working
tree, including unpushed commits and uncommitted changes, to `tools/vrnetlab`.
The copied tree has a non-repository `.git` boundary file, so `git status`
there fails instead of reporting changes from an enclosing lab repository.

Defrost, or the launcher's first run when defrost was skipped, selects a listed
Python (`ECLAB_PYTHON` names one explicitly), creates `.eclab-venv`, and installs
the lock with `pip install --no-index` from the wheelhouse. It then verifies
both tools against the recorded identities, installs them as
`.eclab-venv/bin/containerlab` and `.eclab-venv/share/vrnetlab`, and writes
`.eclab-freeze.env` pointing `CONTAINERLAB_BIN` and `VRNETLAB_DIR` at them.
The launcher clears checkout version controls so deploy uses these frozen tools
without requesting a Git update; the recorded revisions are verified from the
archive metadata.

Nothing is fetched, and host tool selections do not affect the launcher. A
runtime archive without bundled tools, or with tools that differ from the
record, is refused; freeze it again with `--eclab-with-runtime`. Offline mode validates its
artifacts before use and has no runtime network fallback. `--eclab-no-runtime`
leaves runtime mode setup to the launcher. Defrost never deploys the lab.

For failures, use `-t` for ambiguous topology selection, install the producer
edition's provider when missing, select the Containerlab and vrnetlab to bundle before
freezing with runtime, install a Python listed in `python-versions.freeze.txt`
(or set `ECLAB_PYTHON`) on the recipient, and verify a complete wheelhouse, active virtual environment,
tools, and images before freezing offline. Inspect a received archive's
topology, scripts, and package lock before executing its launcher.
