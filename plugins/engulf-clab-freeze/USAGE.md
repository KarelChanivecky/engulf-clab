# Freeze and defrost labs

Install `engulf-clab-freeze` with the producing edition. The eclab edition
provides the first runtime provider. Freeze selects the explicit topology or
the single recognized topology in the current directory. Containerlab YAML is
the base language; see the upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
Plugin controls are conventions layered onto valid Containerlab fields.

```bash
eclab freeze -t lab.clab.yml --output share.tar.gz
eclab freeze -t lab.clab.yml --eclab-with-runtime
eclab freeze -t lab.clab.yml --offline --bundle-image example/router:1
eclab defrost share.tar.gz --into restored
./restored/run-eclab.sh
```

Output defaults to `<lab-directory>/<lab-directory-name>.tar.gz` and must end
in `.tar.gz` or `.tgz`. Freeze stages and publishes atomically. An existing
regular output prompts for overwrite interactively; symlinks are refused. A
workspace lease prevents concurrent freezes. Offline mode also leases managed
tool repositories.

## Modes

| Mode | Python | Containerlab and vrnetlab | Images |
| --- | --- | --- | --- |
| Default lean | Record every installed package name and version; use the producer edition's installed launcher | Record Containerlab JSON version and commit, and vrnetlab Git revision | Keep complete build recipes and literal Dockerfile dependencies; use recipient variables for unavailable root images and actual missing recipe inputs. No captured image archives. |
| `--eclab-with-runtime` | Add a dependency lock and wheelhouse; create a pinned environment at defrost or first launch | Provision recorded revisions when needed and refuse mismatched tools | Same image plan as lean; no captured image archives. |
| `--offline` | Bundle the active eclab virtual environment and require a complete wheelhouse | Bundle the executable and checkout | Bundle required images or use declared offline builds; no network fallback at runtime. |

`--bundle-image IMAGE` is repeatable and requires `--offline`.
`--external-image IMAGE` is repeatable and applies only to non-offline modes;
the recipient supplies that image. The old `--lean` flag is removed. The
shared `--eclab-with-runtime` spelling is kept across editions; the producing
edition selects its provider. A missing provider is an error.

Freeze resolves inherited settings and recursive dependencies from the topology,
packaged Dockerfile image providers, and `engulf_clab.freeze.images.v1` source
declarations. A literal dependency in a Dockerfile stays literal for the
recipient's installed providers or Docker registry to resolve. A nonportable
root image, VM source, or actual missing recipe input in non-offline modes may
become an `${ECLAB_FREEZE_...}` variable; `initialize-env.sh` asks the recipient
for it. Offline mode captures Docker images by immutable ID, checksums each
export, and retains builds only when declared offline rebuildable. Docker
access is needed for capture or `--load-images`; offline use still needs host
Docker and any required QEMU/KVM capabilities.

Freeze copies ordinary lab files subject to `.eclab-freezeignore` (or the
edition's state prefix), excludes runtime state and tracked prior archives,
redacts licenses, removes license clamps and likely license files, and omits
private `.env` values. It refuses generated lab-local license copies. It
never changes the source lab, deploys, pulls, or builds images.

A declared `ECLAB_IMAGE_ARCHIVE` is an authored provisioning input. Lean and
runtime freezes keep its relative path and include the tarball when it is inside
the lab directory and survives the freeze exclusions. An archive outside the
lab or excluded by `.eclab-freezeignore` becomes a recipient variable instead.
These source tarballs are distinct from Docker image snapshots captured by the
freeze planner.

## Archive and launcher

Format 3 records `mode`, `producer_edition`, all installed package versions,
tool identities, image decisions, and license prompts in
`x-engulf-clab-freeze`. `packages.freeze.txt` contains package names and
versions only, with no pip URLs, credentials, or local paths.
`images.freeze.json` records image actions and artifact checksums. Lean
archives include no `wheelhouse/`, `requirements.freeze.txt`, `.eclab-venv/`,
`tools/`, or generated image snapshots. Authored in-scope archive inputs remain
part of the ordinary lab source tree. Runtime archives add the lock and wheelhouse.
Offline archives also include `.eclab-venv/`, `tools/containerlab/`,
`tools/vrnetlab/`, and required image archives. Every archive has
`run-eclab.sh`, `initialize-env.sh`, and `FREEZE-WARNINGS.txt`.

The lean launcher executes the producer edition already installed on the
recipient. It creates no environment, prompts for no compatibility override,
and exports no frozen tool pins. Runtime launchers use a pinned environment;
offline launchers use bundled artifacts and host Docker. With no arguments,
the launcher deploys the frozen topology; arguments replace that default.

Freeze reads contributor-owned state, including PKI's workspace identities and
user catalog. Encrypted exports preserve existing exportable identities; ordinary
user-authority restores can bind automatically to the matching user certificate.

## Defrost

```bash
eclab defrost share.tar.gz --into restored --license router=/pools/routers
eclab defrost share.tar.gz --env ROUTER_IMAGE=router:1 --no-license-prompt
eclab defrost share.tar.gz --force --skip-env-init
```

`--into` defaults to a directory named after the archive. `--force` replaces
only a directory carrying a prior defrost record. `--no-runtime` skips runtime
preparation. `--no-images` skips bundled image selection; `--load-images`
loads selected archives immediately. `--skip-env-init` skips the generated
initializer, which otherwise writes only recipient supplied, nonempty values
to the topology's sibling `.env` file with mode `0600`.

License answers resolve from `--license NODE=VALUE` (or a bare value for all
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
`--force` regenerates warnings from the archive. The launcher does not repeat
lean checks. Normal eclab provisioning of missing tools remains available.

Runtime mode may access package indexes and tool repositories while preparing
recorded revisions, and refuses mismatched tools. Offline mode validates its
artifacts before use and has no runtime network fallback. `--no-runtime`
leaves runtime mode setup to the launcher. Defrost never deploys the lab.

For failures, use `-t` for ambiguous topology selection, install the producer
edition's provider when missing, provide matching tool sources for pinned
provisioning, and verify a complete wheelhouse, active virtual environment,
tools, and images before freezing offline. Inspect a received archive's
topology, scripts, and package lock before executing its launcher.
