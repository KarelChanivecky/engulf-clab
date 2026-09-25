# engulf-clab-freeze

Creates a shareable archive without changing or deploying the source lab:

Install with `python -m pip install engulf-clab-freeze`.

```bash
eclab freeze
eclab freeze -t labs/demo/lab.clab.yml --output demo.tar.gz
eclab freeze -t labs/demo/lab.clab.yml --eclab-with-runtime
eclab freeze -t labs/demo/lab.clab.yml --offline --bundle-image example/router:1
eclab defrost demo.tar.gz --into restored
```

In a lab directory, `freeze` selects its single recognized Containerlab
topology (`*.clab.yml`, `*.clab.yaml`, `clab.yml`, `clab.yaml`, `topology.yml`,
or `topology.yaml`) and defaults to `<lab-directory-name>.tar.gz`. Pass `-t`,
`--topo`, or `--topology` when selection is ambiguous or the topology is
elsewhere. Output must end in `.tar.gz` or `.tgz` and its parent must exist.

Freeze does not deploy, destroy, or inspect the lab. It runs under a
workspace-scoped freeze lease, so two concurrent freezes of the same workspace
block each other; offline mode also leases the managed tool repositories.

## Modes

| Behavior | Default lean | `--eclab-with-runtime` | `--offline` |
| --- | --- | --- | --- |
| Python | Records every installed package name and version; the recipient runs the producing edition's installed launcher | Adds a dependency lock and wheelhouse; defrost or the launcher creates a pinned environment | Bundles the active edition virtual environment |
| Containerlab/vrnetlab | Records Containerlab JSON version and commit, and vrnetlab Git revision | Provisions recorded revisions when needed; refuses mismatched tools | Uses the bundled executable and checkout only |
| Images | Registry references and complete build recipes; unavailable inputs become recipient variables | Same as lean | Bundles required images or declared offline builds; no network fallback |
| Package index | Not used | May fill wheelhouse gaps at defrost or launch | Never used at runtime |

`--bundle-image` is repeatable and requires `--offline`; `--external-image`
is repeatable and applies only to non-offline modes. The lean default
replaces non-portable image inputs with `${ECLAB_FREEZE_...}` recipient
variables, which `initialize-env.sh` asks about. `--offline` fails when the
producing environment lacks a bundled runtime, a required tool, an ordinary
topology image, or a verifiable vrnetlab revision. It remains
platform-specific and needs compatible Docker, Linux networking privileges,
and QEMU/KVM where required. Generated vrnetlab appliance images, vendor VM
inputs, and licenses are never bundled.

## Sanitization and exclusions

The archive includes the sanitized lab, the recorded package manifest, the
mode's tool identities, image decisions, and `run-eclab.sh` in the producing
edition's name (`run-eclab.sh` under eclab, `run-fclab.sh` under fclab). The
copied topology receives `x-engulf-clab-freeze` metadata recording the
format (`3`), the mode, the producing edition, every installed package
version, tool identities, image decisions, and license prompts. Offline
archives add `images.freeze.json` with each captured image's immutable ID
and checksum.

Every node license value becomes `__ECLAB_LICENSE_PROMPT__`, which asks the
recipient for `auto`, a file, pool directory, or `$VARIABLE` at deploy. Every
`*_LIC_CLAMP` entry is removed. Possible license files are excluded by suffix
(`.lic`, `.license`, `.licence`) and reported. Freeze fails if generated
`.<state-prefix-lowercase>/licenses` copies exist in the lab, including the
legacy `.engulf-clab/licenses` location; successfully destroy the licensed lab
first or reconcile legacy state deliberately.

Built-in exclusions cover the active application's managed lab state, virtual
environments, runtime state, tracked prior archives, likely license files,
and the current `clab-<lab>` runtime directory. Add Git-ignore-style patterns
in `.<state-prefix-lowercase>-freezeignore` (`.eclab-freezeignore` for base
eclab). This state-directory prefix is derived from the active application's
short product name, unlike the fixed `ECLAB` label prefix used for the license
marker: branding-only editions may keep `eclab` and share `.eclab/`, while a
superset executable with its own schema pipeline uses that pipeline ID and
therefore gets separate state. Empty excluded directories are omitted. Internal
symlinks are preserved; symlinks escaping the lab are rejected rather than
dereferenced.

Archives created inside the lab are tracked and excluded from later freezes so
they cannot nest. Missing or non-regular tracked outputs are pruned on the next
freeze. An existing regular output prompts before overwrite in an interactive
session, and declining leaves it unchanged; noninteractive execution never
assumes consent. Symlinks and other non-regular destinations are rejected.

## Archive and recipient workflow

Each archive has one sanitized root, named after the archive filename,
containing:

| Entry | Purpose |
| --- | --- |
| Frozen lab and topology | Source copy after exclusions, license redaction, and portable rewrites. |
| `packages.freeze.txt` | Every installed package name and version, no URLs or paths. |
| `requirements.freeze.txt` | Dependency lock; runtime and offline modes only. |
| `wheelhouse/` | Exact wheels; runtime and offline modes only. |
| `initialize-env.sh` | Recipient-run helper that writes supplied environment values to the lab's `.env` (mode 0600). |
| `run-<edition>.sh` | Launcher using the frozen topology, named for the producing edition. |
| `FREEZE-WARNINGS.txt` | Freeze-time acquisition and compatibility warnings. |
| `tools/`, `images/` | Bundled Containerlab/vrnetlab and image archives; offline mode only. |

```bash
tar -xzf demo.tar.gz
cd demo
./run-eclab.sh
./run-eclab.sh destroy -t lab.clab.yml
./run-eclab.sh inspect -t lab.clab.yml
```

The launcher is named for the producing edition and every branch executes
that edition's console script. With no arguments it deploys; arguments
replace that default. A lean launcher runs the installed edition with no
environment and no compatibility prompt. A runtime launcher creates
`.eclab-venv` from the lock and wheelhouse on first use, prepares recorded
Containerlab and vrnetlab revisions (building a pinned Containerlab when the
host lacks them), pins them in `.eclab-freeze.env`, verifies tool identities
on every launch, and rejects tool override flags. An offline launcher uses
only bundled runtime/tools and the host Docker daemon, with no package index
or PATH fallback.

Review the archive and package lock before execution: topologies, scripts,
startup configs, Dockerfiles, and packages are executable or privileged input.

## Defrost

```bash
eclab defrost demo.tar.gz --into restored
eclab defrost demo.tar.gz --license router=/pools/routers
eclab defrost demo.tar.gz --env ROUTER_IMAGE=router:1 --no-license-prompt
eclab defrost demo.tar.gz --force --skip-env-init
```

`--into` defaults to a directory named after the archive. `--force` replaces
only a directory carrying a prior defrost record. `--no-runtime` skips
runtime preparation and leaves it to the launcher. `--no-images` skips
bundled image selection; `--load-images` loads selected archives
immediately. `--env NAME=VALUE` feeds the recipient initializer
noninteractively; `--skip-env-init` skips it. `initialize-env.sh` writes
only nonempty answers to the topology's sibling `.env` with mode `0600`.

License answers resolve from `--license NODE=VALUE` (or a bare value for all
nodes), then `ECLAB_LICENSE_<NODE>`, then `ECLAB_LICENSE`, then an
interactive prompt. Answers may be `auto` (registered pool request), an
existing file or pool directory, or a `$VARIABLE` for deploy. License answers
are neither frozen nor recorded.

Defrost requires one archive root and rejects escaping members, invalid image
checksums, and archives whose contributor or runtime provider is missing.
Formats 1 and 2 keep their original restore rules; format 3 selects the
recorded producer edition's provider, so a runtime or offline archive needs
that edition's provider installed on the recipient. Lean defrost compares the
package manifest (extra recipient packages are allowed), Containerlab
`version -j` version and commit, and vrnetlab Git revision once, appends
mismatches to `FREEZE-WARNINGS.txt`, and records them. Runtime mode may reach
package indexes and tool repositories while provisioning recorded revisions
and refuses mismatched tools; offline mode validates its artifacts and has no
network fallback. Defrost never deploys the lab.

## Failure semantics and troubleshooting

Freeze stages beside the destination and renames the final archive only after
copying, sanitization, image planning, package collection, offline checks, and
compression succeed. Failure leaves no partial requested output.

- Pass `-t` when topology selection is ambiguous.
- Choose a new output path when overwrite cannot be confirmed.
- Runtime/offline modes require a verifiable Containerlab version and commit
  (and vrnetlab revision offline); run them from an environment with the
  selected tools.
- A missing wheelhouse warning means a runtime archive's launcher will fall
  back to its package index; offline mode instead fails without a complete
  wheelhouse.
- For offline failures, freeze from a virtual environment containing the
  edition, with Containerlab, vrnetlab, and every required image present.
- If an old archive is unexpectedly excluded, remove it and freeze again; stale
  tracking records are pruned automatically.
- Replace an escaping symlink with a lab-local copy or exclude it explicitly.
- Install the producer edition's provider when defrost reports it missing.
