# Freeze and defrost labs

Install `engulf-clab-freeze` with the producing edition. It installs the
license-pool plugin so defrost can inspect pools registered in that plugin's
state namespace. The eclab edition provides the first runtime provider. Freeze
selects the single recognized topology in the positional lab directory, which
defaults to `.`. Use `-t` to select a topology file explicitly; it cannot be
combined with a positional directory. Containerlab YAML is the base language;
see the upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
Plugin controls are conventions layered onto valid Containerlab fields.

```bash
eclab freeze                         # current directory
eclab freeze labs/demo --eclab-output share.tar.gz
eclab freeze labs/demo --eclab-with-runtime --eclab-output demo-runtime.run
eclab freeze labs/demo --eclab-offline --eclab-bundle-image example/router:1
eclab freeze -t labs/demo/lab.clab.yml
eclab defrost share.tar.gz --eclab-output restored
./restored/run-eclab.sh
./demo-runtime.run                 # automatically defrosts into ./demo-runtime
./demo-runtime/run-eclab.sh        # deploys the restored lab
```

Lean output defaults to `./<lab-directory-name>.tar.gz` in the invocation
directory. Runtime and offline output defaults to `./<lab-directory-name>.run`.
Lean destinations must end in `.tar.gz` or `.tgz`; runtime and offline
destinations must end in `.run`. Freeze stages and publishes atomically. An
existing regular output prompts for overwrite interactively; symlinks are
refused. A workspace lease prevents concurrent freezes. Offline mode also
leases managed tool repositories.

When freeze or defrost is run through `sudo`, its generated archive, expanded
lab tree, and freeze bookkeeping state are returned to the invoking user's
ownership so that user can update or run the output afterward.

## Modes

| Mode | Python | Containerlab and vrnetlab | Images |
| --- | --- | --- | --- |
| Default lean | Record every installed package name and version; use the producer edition's installed launcher | Record Containerlab JSON version and commit, and vrnetlab Git revision | Keep complete build recipes and literal Dockerfile dependencies; use recipient variables for unavailable root images and actual missing recipe inputs. No captured image archives. |
| `--eclab-with-runtime` | Write an executable `.run` package containing `runtime/`, `lab.tgz`, and `defrost.sh`; build the pinned venv before normal defrost | Bundle the producer's Containerlab executable and vrnetlab working tree beside the wheelhouse; defrost attaches them to the restored lab | Same image plan as lean; no captured image archives. |
| `--eclab-offline` | Write an executable `.run` with a defrost venv under `runtime/` and the complete offline lab in `lab.tgz` | Bundle the executable and checkout in the offline lab | Bundle required images or use declared offline builds; no network fallback at runtime. |

Offline archives rewrite Python console commands to use the interpreter beside
them and omit the virtual environment's creation command. Direct commands such
as `.eclab-venv/bin/pip freeze` therefore do not depend on the producer's path.

`--eclab-bundle-image IMAGE` is repeatable and requires `--eclab-offline`.
`--eclab-external-image IMAGE` is repeatable and applies only to non-offline modes;
the recipient supplies that image. The old `--lean` flag is removed. The
shared `--eclab-with-runtime` spelling is kept across editions; the producing
edition selects its provider. A missing provider is an error.

## Runtime bundles and dependencies

Runtime-bearing packages are self-extracting executable `.run` files. Running
one automatically extracts its payload to a temporary directory and defrosts
the lab into `./<package-name>`. It also runs `initialize-env.sh` and the normal
recipient license workflow. When no license pool is registered, defrost offers
to create a directory and initialize it with the edition's `init-license-pool`
command. The pool starts empty; add entitled license files to it afterward. On
completion defrost points to `FREEZE-README.md` in the restored lab for
lab-specific run instructions. It refuses to replace an existing output
directory. Starting the package needs only a shell, `tail`, `tar`, `gzip`, and
standard Linux file utilities; the included runtime performs defrost without
an installed eclab or Docker. Runtime mode may need a supported host Python to
build its included venv the first time. For example:

```bash
./demo-runtime.run
./demo-runtime/run-eclab.sh
```

Pass an output directory as the first argument to choose a different lab
location, for example `./demo-runtime.run restored`. The named form
`--eclab-output DIRECTORY` is also supported immediately after the package
name, before any other defrost options. For example:
`./demo-runtime.run --eclab-output restored --eclab-license router=/pool`.

Interactive runtime defrost asks whether to configure the bundled Containerlab
for sudo-less use. This grants the account root-equivalent Containerlab and
Docker access. Answer yes to run the existing `sudoless` setup for the restored
venv; answer no to leave it unchanged. The command uses `sudo` for the
Containerlab ownership and group changes. Noninteractive defrost skips this
offer; run `./run-eclab.sh sudoless` later as the lab owner if needed.

The `--eclab-with-runtime` package contains `runtime/` (the dependency lock,
wheelhouse, Python version list, and pinned tools), `lab.tgz` (the frozen lab
archive), `defrost.sh`, and a `README.md` guide. Running the package invokes
`defrost.sh`, which builds the bundled edition's venv from the wheelhouse when
needed and uses it to run normal `defrost lab.tgz`. Defrost runs
`initialize-env.sh`, resolves recipient licenses, prepares the lab runtime, and
writes real recipient selections only
to the expanded lab. A defrosted lab contains the venv and tools unless
`--eclab-no-runtime` was passed; in that case its launcher can build the venv
on first run.

Offline packages use the same outer layout and automatically defrost when run.
Their `runtime/` carries the venv used to run defrost and attach to the
expanded lab. Their `lab.tgz` contains the offline lock, wheelhouse, tools, and
image archives without a duplicate venv. Running the `.run` resolves recipient
values and expands the lab.

The `--eclab-with-runtime` bundle requires a supported host Python listed in
`runtime/python-versions.freeze.txt` the first time `defrost.sh` builds its
venv. An offline bundle already carries that venv. Neither bundle requires an
installed eclab or package index; the self-extractor uses shell/archive
utilities only. Deploy still requires Docker and any kernel, device, or
networking facilities required by Containerlab.

Defrost checks declared host dependencies during extraction, after runtime
setup, and continues while flagging missing dependencies as warnings. Its
completion notes and dependency report follow the runtime setup output, with
warnings last. `check-dependencies.sh` also marks each missing item as a warning.
Before a requested operation starts, the restored lab's launcher checks only
that operation's applicable requirements and stops with a clear list when one
is missing. Docker is required for deployment. Go is checked when Containerlab
must be built from source. `make`, `qemu-img`, and `qemu-system-x86_64` are
checked when the topology opts into vrnetlab image building and those images
are not supplied. Already available local images satisfy that build
requirement. Schema providers can also declare host libraries and scope
requirements by command, topology feature, and packaged artifact. These checks
report prerequisites; they do not install them.

Run `./check-dependencies.sh` in the restored lab to repeat the non-blocking
warning report. Pass an operation such as `deploy` to report only that
operation's requirements. Lean archives also include the reporter after defrost.

Freeze resolves inherited settings and recursive dependencies from the topology,
packaged Dockerfile image providers, and `engulf_clab.freeze.images.v1` source
declarations. A literal dependency in a Dockerfile stays literal for the
recipient's installed providers or Docker registry to resolve. A nonportable
root image, VM source, or actual missing recipe input in non-offline modes may
become an `${ECLAB_FREEZE_...}` variable; `initialize-env.sh` asks the recipient
for it. When a VM source already uses a single variable such as
`${FCLAB_DEMO_IMAGE:-}`, lean freeze keeps that expression and prompts for its
original name. A vrnetlab VM input is supplied with
`--eclab-vrnetlab-image NODE=PATH` at deploy time; lean freeze does not create a
replacement image-path variable. Existing build-context paths such as `.` stay
literal when their directory is included, even if freeze exclusions omit files
from the context. Offline mode captures Docker images by immutable ID and checksums
each export. Authored node archives are selected through `ECLAB_IMAGE_ARCHIVE`;
dependency-only and plugin-generated service images are recorded in
`images.freeze.json`. The topology selects that manifest with
`ECLAB_IMAGE_ARCHIVE_MANIFEST`, allowing the image-archive provider to load every
snapshot during deploy or redeploy. Freeze retains builds only when declared
offline rebuildable. Docker access is needed for capture; offline use still
needs host Docker and any required QEMU/KVM capabilities.

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
and license prompts in the separate `freeze.json` file. The Containerlab
topology remains ordinary Containerlab YAML. `packages.freeze.txt` contains
package names and versions only, with no pip URLs, credentials, or local paths.
`images.freeze.json` records image actions and artifact checksums. Lean
archives include no `wheelhouse/`, `requirements.freeze.txt`, `.eclab-venv/`,
`tools/`, or generated image snapshots. Authored in-scope archive inputs remain
part of the ordinary lab source tree. A runtime bundle keeps the runtime lock,
wheelhouse, `python-versions.freeze.txt`, and pinned tools under outer
`runtime/`; its inner `lab.tgz` contains the frozen lab and `defrost.sh` performs
the ordinary expansion and copies runtime files into the restored lab.
Offline archives also include `.eclab-venv/`, `tools/containerlab/`,
`tools/vrnetlab/`, and required image archives. Defrost leaves image loading to
the `engulf-clab-image-archive` provider during deploy. The frozen topology
selects the image manifest, which supplies archives for authored nodes,
dependency-only images, and plugin-generated service nodes.
Every lab archive has
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
development tools are retained only as provenance. A runtime bundle builds
the edition venv under outer `runtime/`, then normal defrost copies it and the
pinned tools into the lab. Offline launchers use bundled artifacts and host
Docker. With no arguments, the launcher deploys the frozen topology; arguments
replace that default.

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
preparation. `--eclab-no-images` skips bundled image selection. Defrost only
points the topology at bundled archives; the image-archive provider loads them
during deploy or redeploy. `--eclab-skip-env-init` skips the generated
initializer, which otherwise writes only recipient supplied, nonempty values
to the topology's sibling `.env` file with mode `0600`.

License answers resolve from `--eclab-license NODE=VALUE` (or a bare value for all
nodes), `ECLAB_LICENSE_<NODE>`, `ECLAB_LICENSE`, auto license, then an
interactive prompt. Answers may be `auto`, an existing file or pool directory,
or a `$VARIABLE` for deploy. `auto` is retained as a request for the active
license provider to allocate at deploy; a defrost preflight that cannot see a
pool does not reject that request. Deployment reports whether a matching pool
is actually available. License answers are neither frozen nor written to the
defrost record.

Defrost requires one archive root and a topology with supported metadata. It
rejects escaping members, invalid image checksums, and missing contributors.
Formats 1 and 2 keep their original restore rules. Format 3 selects the
recorded producer edition's provider. Lean defrost compares the package
manifest (extra recipient packages are allowed), Containerlab `version -j`
version and commit, and vrnetlab Git revision. It reports missing or
mismatched values once, appends them to `FREEZE-WARNINGS.txt`, and records them.
`--eclab-force` regenerates warnings from the archive. The launcher does not repeat
lean checks. Normal eclab provisioning of missing tools remains available.

A runtime bundle assumes a supported Python on the recipient. Freeze captures the
producer's installed packages as they are: recorded local wheels are copied,
editable projects are built from their current source, and other pure-Python
installations are repacked from their installed files. Only packages it cannot
supply itself are downloaded, and freeze fails unless the wheelhouse is
complete. It then adds compiled wheels for every CPython minor from 3.12 up to
the producer's own and lists the minors that resolved in
`python-versions.freeze.txt`. Freeze also copies the selected Containerlab
executable to `runtime/tools/containerlab/bin/containerlab` and the vrnetlab
working tree, including unpushed commits and uncommitted changes, to
`runtime/tools/vrnetlab`.
The copied tree has a non-repository `.git` boundary file, so `git status`
there fails instead of reporting changes from an enclosing lab repository.

`defrost.sh` selects a listed Python (`ECLAB_PYTHON` names one explicitly),
creates the bundled `.eclab-venv`, and installs the lock with
`pip install --no-index` from `runtime/wheelhouse/`. The normal defrost command
then copies the venv and checks both tools against the recorded identities,
installs them as
`.eclab-venv/bin/containerlab` and `.eclab-venv/share/vrnetlab`, and writes
`.eclab-freeze.env` pointing `CONTAINERLAB_BIN` and `VRNETLAB_DIR` at them.
The launcher clears checkout version controls so deploy uses these frozen tools
without requesting a Git update; the recorded revisions are verified from the
archive metadata.

Nothing is fetched to build the runtime, and host tool selections do not affect
the launcher. A runtime bundle without bundled tools, or with tools that
differ from the record, is refused; freeze it again with
`--eclab-with-runtime`. Offline mode validates its artifacts before use and
has no runtime network fallback. `--eclab-no-runtime` leaves the restored lab's
runtime setup to its launcher. Defrost never deploys the lab.

For failures, use `-t` for ambiguous topology selection, install the producer
edition's provider when missing, select the Containerlab and vrnetlab to bundle before
freezing with runtime, install a Python listed in `python-versions.freeze.txt`
(or set `ECLAB_PYTHON`) on the recipient, and verify a complete wheelhouse, active virtual environment,
tools, and images before freezing offline. Inspect a received archive's
topology, scripts, and package lock before executing its launcher.
