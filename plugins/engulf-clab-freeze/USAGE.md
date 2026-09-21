# engulf-clab-freeze

New archives use format 2. Defrost accepts legacy format 1 and format 2; older
readers reject format 2. Installed contributors may add namespaced arguments,
sanitize staged files, record authenticated metadata, resolve recipient
bindings, and restore state before the destination is published. A required
missing contributor fails without leaving a partial destination.

Creates a shareable archive without changing or deploying the source lab, and
expands a received archive back into a runnable one:

Install with `python -m pip install engulf-clab-freeze`. The beta release
requires the Engulf 1.0 plugin APIs used for packaging-declared dependency
ordering and includes `defrost`.

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

Freeze does not deploy or destroy the lab. It reads image metadata and may
export existing Docker images; it never builds, pulls, or loads an image. It runs under a
workspace-scoped freeze lease, so two concurrent freezes of the same workspace
block each other.

## Default, lean, and offline bundles

Default freeze includes the image dependencies a recipient cannot otherwise
obtain or rebuild. Installed image owners describe their recipes through
`engulf_clab.freeze.images.v1`; freeze resolves inherited node settings and walks
the complete declared image dependency graph, including Dockerfile `FROM` and
external `COPY --from` references. This classification uses the selected source,
not an image-name prefix or filename extension.

| Selected source | Default freeze |
| --- | --- |
| Verified registry image, such as Debian | Record the registry identity; omit image bytes. |
| Complete lab-local Dockerfile/context | Keep the recipe and recursively resolve its bases; omit the output image. |
| Declared saved-image archive | Include it once and record its exact source/retag selection. |
| vrnetlab with a lab-local QCOW included in the archive | Keep its input and builder selection for recipient rebuilding. |
| Build with external, excluded, missing, or otherwise unaccounted-for inputs | Export the existing resulting image and disable that build in the portable copy. |
| Unknown acquisition source | Export the existing local image, or fail if unavailable. |

Dockerfile file inputs must survive freeze exclusions. Context completeness is
conservative: an omitted context file or extra Docker build arguments can require
capturing the output even when a particular build would not use that input.
Normal rebuilds may use package repositories or Dockerfile downloads and are not
a promise of byte-identical outputs. Use `--bundle-image IMAGE` to capture an
exact existing image instead. Repeat it for additional roots or dependencies.

Freeze probes registry manifests without pulling layers. When a local tag
exists, the remote image must match its configuration identity; another image
under the same registry tag does not substitute for it. A failed or unavailable
probe means unknown availability, not proof of an offline-only source. Registry
access uses the caller's Docker configuration; recipient access to private
registries remains an assumption. `--external-image IMAGE` explicitly leaves
an image for the recipient to supply and records that exception. It conflicts
with `--bundle-image` for the same image and is unavailable with `--offline`.

```bash
eclab freeze -t lab.clab.yml
eclab freeze -t lab.clab.yml --lean
eclab freeze -t lab.clab.yml --bundle-image example/app:1
eclab freeze -t lab.clab.yml --external-image registry.example/team/router:1
```

`--lean` replaces non-portable image selections with `${ECLAB_FREEZE_...}`
variables and includes no newly exported image artifacts. It replaces saved-image
archive paths, VM input paths, incomplete build-input paths, and unknown root
image references. Referenced lab-local image archives and VM inputs are omitted
too; other lab files still follow normal exclusions. Complete Dockerfile recipes
and public image tags stay intact. An unavailable recursive base gets a recipient
archive variable so its expected tag remains usable by its Dockerfile. The
generated `initialize-env.sh` asks for these values alongside existing topology
variables. It carries no source path defaults. Unresolved root image expressions
are allowed only in lean mode. `--lean` conflicts with `--offline` and
`--bundle-image`; it does not parameterize IP addresses, ports, or unrelated lab
settings.

Default freeze requires every selected image to resolve. Missing required
artifacts fail atomically with the dependency chain. Export requires Docker
daemon authorization; an existing declared archive can be packaged without
Docker. Images are saved by immutable image ID, deduplicated, and recorded with
checksums and platform information when available.

Archive-backed images need tag references: Docker cannot retag a loaded image
as `name@sha256:...`. Registry digest references may remain remote, but a digest
reference requiring capture fails with guidance to select a tag or explicitly
leave it external. Freeze does not publish an archive that cannot restore its
requested reference.

| Behavior | Normal | `--offline` |
| --- | --- | --- |
| Python runtime | Reuses or installs locked packages | Bundles the active eclab virtual environment |
| Containerlab/vrnetlab | Uses recorded provenance and normal resolution | Uses bundled executable and checkout only |
| Registry images | May be pulled by the recipient | Bundled from the local daemon |
| Build outputs | Omitted when the included recipe is complete | Bundled unless the provider establishes offline rebuildability |
| vrnetlab image | Rebuild from included input, otherwise bundle output | Bundle output; no recipient QCOW is required |
| Package index | May fill wheelhouse gaps | Never used at runtime |

Offline creation fails if eclab is not running in a virtual environment, a
required tool is unavailable, or a required image has neither a usable archive
nor a local Docker image.
It remains platform-specific and needs compatible Docker, Linux networking
privileges, and QEMU/KVM where required. License files and allocations remain
excluded in every mode. VM inputs are never imported automatically from outside
the lab; default freeze captures the resulting image instead.

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
expressions, and the recipient supplies their own file after defrost. The archive
also contains a generated `initialize-env.sh` helper; it asks for values for the
variables still referenced by the topology and writes only non-empty answers to
the topology's expected sibling env file. Freeze fails if generated
`.<state-prefix-lowercase>/licenses` copies exist in the lab, including the
legacy `.engulf-clab/licenses` location; successfully destroy the licensed lab
first or reconcile legacy state deliberately.

License selectors and `*_LIC_CLAMP` values are sanitized at every declaration
origin: defaults, kinds, groups, and nodes, including shadowed and unused entries.
Optional site-setting contributors use the same inventory. Defrost resolves
inherited license prompts per node and respects inherited archive selections.
Offline image collection and vrnetlab input redaction likewise resolve inherited
node image/environment controls before writing the portable copy.

Built-in exclusions cover the active application's managed lab state, virtual
environments, caches, likely license files, private `*.env` files, and the
current `clab-<lab>` runtime directory. Hidden `.engulf-clab-lab-*.clab.yml`
and `.engulf-clab-lab-*.clab.yaml` files produced by the lab writer are also
excluded: they are deploy-time renderings, not portable authored topology. Add
Git-ignore-style patterns in
`.<state-prefix-lowercase>-freezeignore` (`.eclab-freezeignore` for base
eclab). The reserved source name `initialize-env.sh` is replaced by the
generated recipient helper. This state-directory prefix is derived from the
active application's short product name, unlike the fixed `ECLAB` label prefix
used for the license marker: branding-only editions may keep `eclab` and share
`.eclab/`, while a
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
| `initialize-env.sh` | Recipient-side helper that writes topology variables into its private env file. |
| `run-eclab.sh` | Launcher using the frozen topology. |
| `images.freeze.json` | Acquisition decisions, checksums, image identities, and build dependencies. |
| `images/` | Exported images and copied external image archives, when needed. |

The frozen topology selects its manifest with
`env.ECLAB_IMAGE_ARCHIVE_MANIFEST`. The archive provider makes its images
available to both runtime nodes and recursive build dependencies. Captured
outputs replace their build controls, including inherited settings. Normal
included build inputs are rewritten relative to the topology. The source lab
is unchanged.

```bash
tar -xzf demo.tar.gz
cd demo
./initialize-env.sh
./run-eclab.sh
./run-eclab.sh destroy -t lab.clab.yml
./run-eclab.sh inspect -t lab.clab.yml
```

With no arguments the launcher deploys; arguments replace that default. A
normal launcher reuses a compatible eclab. Interactively, the recipient may
accept an incompatible installed eclab or a user-site installation; otherwise
the launcher creates `.eclab-venv` from the wheelhouse/package index. An
offline launcher uses only bundled runtime/tools, disables checkout updates,
and provisions bundled images through the image archive provider. Both use the host Docker daemon and
privileges.

Review the archive and package lock before execution: topologies, scripts,
startup configs, Dockerfiles, and packages are executable or privileged input.

## Expanding an archive

`defrost` is the reverse command: it expands one archive, prepares the runtime,
selects bundled Docker image archives, asks for the licenses freeze redacted,
and removes the `x-engulf-clab-freeze` metadata so the result is an ordinary
lab. It restores the executable permission on `initialize-env.sh` and runs it
automatically unless `--skip-env-init` is supplied. It never deploys and never
contacts a registry.

```bash
eclab defrost demo.tar.gz
eclab defrost demo.tar.gz --into labs/demo
eclab defrost demo.tar.gz --license router=/pools/routers --license '$SITE_POOL'
eclab defrost demo.tar.gz --no-license-prompt --no-runtime
eclab defrost demo.tar.gz --skip-env-init
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
| `--skip-env-init` | Skip running `initialize-env.sh` during defrost. |

The archive must be a `.tar.gz` or `.tgz` regular file with exactly one root
directory, and the topology carrying `x-engulf-clab-freeze` selects itself.
Freeze stamps exactly one topology per archive, so selection is never ambiguous
and defrost has no topology option. Members that escape the root, unsupported
freeze formats, and archives without freeze metadata are rejected. Defrost runs
under a lease on its destination, so two concurrent expansions into one
directory block each other. Defrost removes legacy lab-writer topology outputs
before publishing, so an older archive cannot restore a stale second topology.

Licenses are answered in order: `--license`, then `ECLAB_LICENSE_<NODE_NAME>`,
then `ECLAB_LICENSE`, then an interactive prompt. Each answer is a license file,
a pool directory, or a `$VARIABLE` that deploy resolves later; paths are stored
absolute and must exist. A node nobody answers keeps its marker, and deploy
prompts for it as usual. Answers are never logged or written to the defrost
record: an expanded lab holds real license selections, so do not commit or
re-share that directory. Freeze redacts them again on the next archive.

Defrost runs `./initialize-env.sh` before image, vrnetlab, and license
resolution. It prompts once for each referenced variable, in stable name order;
an empty answer refuses that variable and writes nothing. Values are appended
using the parser's supported dotenv syntax to the expected sibling file, such as
`lab.env`, with mode `0600`. The helper never copies the source owner's excluded
env file and does not log the entered values. Use `--skip-env-init` to skip
running it and leave the env file untouched, or run it manually later to
replace or add answers; existing file contents are preserved.

New archives validate their image manifest and checksums before publication.
Their explicit acquisition selections are retained; an incidental tarball does
not replace a recorded recipe. Deploy loads and retags manifest images from
their declared artifacts, including build-only dependencies. `--load-images`
also loads the manifest's bundled dependencies immediately, deduplicating loads
and restoring target tags. `--no-images` disables manifest selection in the
restored topology.

For legacy archives without an image plan, any `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, or `.txz` file in
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
  Containerlab/vrnetlab, and ensure required images exist in Docker or declared archives.
- If an old archive is unexpectedly excluded, remove it and freeze again; stale
  tracking records are pruned automatically.
- Replace an escaping symlink with a lab-local copy or exclude it explicitly.
- Defrost stages beside the destination and renames only after expansion,
  sanitization reversal, image selection, and license answers succeed. A failure
  leaves no partial destination, and a replaced directory is restored.
- Pass `--into` when the archive filename does not name the directory you want.
- For a lean or legacy archive with a missing vrnetlab input, supply its recipient
  variable and rebuild. Default archives with captured outputs need no QCOW.
- If a registry probe cannot establish availability, make the selected image
  available locally, restore registry access, use `--lean`, or declare the
  intended recipient dependency with `--external-image`.
- A manifest checksum failure means the artifact no longer matches its recorded
  content; recreate or obtain an intact freeze rather than changing the checksum.
- If runtime preparation fails, run `./run-eclab.sh` in the expanded lab: it
  retries the same installation interactively.
