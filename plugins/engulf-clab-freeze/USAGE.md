# engulf-clab-freeze

New archives use format 2. Defrost accepts legacy format 1 and format 2; older
readers reject format 2. Installed contributors may add namespaced arguments,
sanitize staged files, record authenticated metadata, resolve recipient
bindings, and restore state before the destination is published. A required
missing contributor fails without leaving a partial destination.

Creates a shareable archive without changing or deploying the source lab, and
expands a received archive back into a runnable one:

Install with `python -m pip install engulf-clab-freeze`. Version 0.2.0 and later
requires the Engulf 1.2 plugin APIs used for packaging-declared dependency
ordering. Version 0.3.0 adds `defrost`.

```bash
eclab freeze
eclab freeze -t labs/demo/lab.clab.yml --output demo.tar.gz
eclab defrost demo.tar.gz
eclab defrost demo.tar.gz --into labs/demo --license router=/pools/routers
```

In a lab directory, `freeze` selects its single recognized Containerlab
topology (`*.clab.yml`, `*.clab.yaml`, `clab.yml`, `clab.yaml`, `topology.yml`,
or `topology.yaml`) and defaults to `<lab-directory-name>.tar.gz`. Pass `-t`,
`--topo`, or `--topology` when selection is ambiguous or the topology is
elsewhere. Output must end in `.tar.gz` or `.tgz` and its parent must exist.

Freeze does not deploy, destroy, or inspect the lab. It runs under a
workspace-scoped freeze lease, so two concurrent freezes of the same workspace
block each other.

## Normal and offline bundles

| Behavior | Normal | `--offline` |
| --- | --- | --- |
| Python runtime | Reuses or installs locked packages | Bundles the active eclab virtual environment |
| Containerlab/vrnetlab | Uses recorded provenance and normal resolution | Uses bundled executable and checkout only |
| Ordinary Docker images | May be pulled by the recipient | Bundled from the local daemon and loaded when missing |
| vrnetlab VM input | External input is copied and rewritten relative | Recipient supplies entitled input and rebuilds locally |
| Package index | May fill wheelhouse gaps | Never used at runtime |

Offline creation fails if eclab is not running in a virtual environment, a
required tool is unavailable, or an ordinary topology image is absent locally.
It remains platform-specific and needs compatible Docker, Linux networking
privileges, and QEMU/KVM where required. Generated vrnetlab appliance images,
vendor VM inputs, and licenses are never bundled.

## Sanitization and exclusions

The archive includes the sanitized lab, exact package lock, best-effort
wheelhouse, non-secret source provenance, and `run-eclab.sh`. The copied
topology receives `x-engulf-clab-freeze` metadata describing the format,
application, packages, tools, license policy, and offline mode.

Every node license value becomes `__ECLAB_LICENSE_PROMPT__`, which asks the
recipient for a file, pool directory, or `$VARIABLE` at deploy. Every
`*_LIC_CLAMP` entry is removed. Possible license files are excluded by suffix
(`.lic`, `.license`, `.licence`) and reported. A lab's private `*.env` files
are excluded and reported the same way: the topology keeps its unresolved
expressions, and the recipient supplies their own file after defrost. Freeze fails if generated
`.<state-prefix-lowercase>/licenses` copies exist in the lab, including the
legacy `.engulf-clab/licenses` location; successfully destroy the licensed lab
first or reconcile legacy state deliberately.

Built-in exclusions cover the active application's managed lab state, virtual
environments, caches, likely license files, private `*.env` files, and the
current `clab-<lab>` runtime directory. Add Git-ignore-style patterns in
`.<state-prefix-lowercase>-freezeignore` (`.eclab-freezeignore` for base
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
| `requirements.freeze.txt` | Exact wrapper, active plugin, and transitive package versions. |
| `wheelhouse/` | Available exact local or downloaded wheels; may be absent. |
| `.eclab-freeze.env` | Verifiable non-secret Containerlab/vrnetlab repository and revision provenance. |
| `run-eclab.sh` | Launcher using the frozen topology. |

Normal mode copies configured external vrnetlab inputs into the staged lab,
rewrites them as relative paths, and records hashes. Offline mode removes those
inputs and requires the entitled recipient to select them locally.

```bash
tar -xzf demo.tar.gz
cd demo
./run-eclab.sh
./run-eclab.sh destroy -t lab.clab.yml
./run-eclab.sh inspect -t lab.clab.yml
```

With no arguments the launcher deploys; arguments replace that default. A
normal launcher reuses a compatible eclab. Interactively, the recipient may
accept an incompatible installed eclab or a user-site installation; otherwise
the launcher creates `.eclab-venv` from the wheelhouse/package index. An
offline launcher uses only bundled runtime/tools, disables checkout updates,
and may load bundled ordinary images. Both use the host Docker daemon and
privileges.

Review the archive and package lock before execution: topologies, scripts,
startup configs, Dockerfiles, and packages are executable or privileged input.

## Expanding an archive

`defrost` is the reverse command: it expands one archive, prepares the runtime,
selects bundled Docker image archives, asks for the licenses freeze redacted,
and removes the `x-engulf-clab-freeze` metadata so the result is an ordinary
lab. It never deploys and never contacts a registry.

```bash
eclab defrost demo.tar.gz
eclab defrost demo.tar.gz --into labs/demo
eclab defrost demo.tar.gz --license router=/pools/routers --license '$SITE_POOL'
eclab defrost demo.tar.gz --no-license-prompt --no-runtime
```

| Option | Meaning |
| --- | --- |
| `--into DIRECTORY` | Destination; defaults to the archive name without its suffix, in the invocation directory. |
| `--force` | Replace a destination an earlier defrost created; any other directory is refused. |
| `--license NODE=VALUE` | Answer one node's frozen prompt. Repeatable. A bare `VALUE` answers every prompted node. |
| `--no-license-prompt` | Keep the markers and let deploy resolve them. |
| `--no-runtime` | Skip runtime preparation and leave it to `run-eclab.sh`. |
| `--no-images` | Skip bundled image archive selection. |
| `--load-images` | Load matched bundled archives into Docker now instead of at deploy. Needs Docker and container-runtime authorization. |

The archive must be a `.tar.gz` or `.tgz` regular file with exactly one root
directory, and the topology carrying `x-engulf-clab-freeze` selects itself.
Freeze stamps exactly one topology per archive, so selection is never ambiguous
and defrost has no topology option. Members that escape the root, unsupported
freeze formats, and archives without freeze metadata are rejected. Defrost runs
under a lease on its destination, so two concurrent expansions into one
directory block each other.

Licenses are answered in order: `--license`, then `ECLAB_LICENSE_<NODE_NAME>`,
then `ECLAB_LICENSE`, then an interactive prompt. Each answer is a license file,
a pool directory, or a `$VARIABLE` that deploy resolves later; paths are stored
absolute and must exist. A node nobody answers keeps its marker, and deploy
prompts for it as usual. Answers are never logged or written to the defrost
record: an expanded lab holds real license selections, so do not commit or
re-share that directory. Freeze redacts them again on the next archive.

Any `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, or `.txz` file in
the lab is inspected as a `docker save` stream, and a node whose image matches a
reference the archive carries gets `ECLAB_IMAGE_ARCHIVE` pointing at it, so
`engulf-clab-image-archive` loads that image at deploy instead of pulling.
Offline bundles use their own `tools/docker/images.txt` listing. A node that
already declares an archive, a vrnetlab-built node, and an image no bundled
archive carries are all left alone, since a declared archive suppresses the
registry fallback. Selection needs no Docker; only `--load-images` does.

Runtime preparation restores the launcher and bundled tool permissions. An
offline archive must contain a complete `.eclab-venv`, Containerlab executable,
and vrnetlab checkout, and its console-script shebangs are repointed at the new
location. A normal archive keeps the current installation when it already
matches `requirements.freeze.txt`, and otherwise builds `.eclab-venv` from the
wheelhouse after publication, exactly as the launcher would; a failure there is
reported, leaves no partial environment, and defers to `run-eclab.sh`.

Defrost writes `.<state-prefix-lowercase>-defrost.json` in the expanded lab with
the removed freeze provenance, the source archive name, and every note it
reported. `--force` uses that file to recognize a directory it may replace.

## Failure semantics and troubleshooting

Freeze stages beside the destination and renames the final archive only after
copying, sanitization, package collection, offline checks, and compression
succeed. Failure leaves no partial requested output.

- Pass `-t` when topology selection is ambiguous.
- Choose a new output path when overwrite cannot be confirmed.
- Warnings about missing wheels never fail a freeze; they mean a normal archive
  can fall back to its package index, so it is not guaranteed offline. Offline
  mode bundles the runtime itself and does not use the wheelhouse.
- For offline failures, use the installed eclab virtual environment, resolve
  Containerlab/vrnetlab, and ensure ordinary images exist in Docker.
- If an old archive is unexpectedly excluded, remove it and freeze again; stale
  tracking records are pruned automatically.
- Replace an escaping symlink with a lab-local copy or exclude it explicitly.
- Defrost stages beside the destination and renames only after expansion,
  sanitization reversal, image selection, and license answers succeed. A failure
  leaves no partial destination, and a replaced directory is restored.
- Pass `--into` when the archive filename does not name the directory you want.
- If defrost reports a node still needs an entitled vrnetlab image input, supply
  it locally and rebuild; offline archives never carry vendor VM inputs.
- If runtime preparation fails, run `./run-eclab.sh` in the expanded lab: it
  retries the same installation interactively.
