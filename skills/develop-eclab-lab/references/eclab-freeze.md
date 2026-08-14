# engulf-clab-freeze

Creates a shareable frozen lab without changing the source directory:

```bash
python -m pip install engulf-clab-freeze
```

```bash
eclab freeze
```

`freeze` is an Engulf control goal, not a Containerlab subcommand. It preempts
the wrapped executable and runs under a workspace-scoped freeze lease. It does
not deploy, destroy, or inspect the lab.

## Contents

- Topology and output selection
- Normal versus strict offline contents
- Sanitization, ignore, symlink, and archive-tracking rules
- [Archive layout and provenance](#archive-layout-and-provenance)
- [Recipient workflow](#recipient-workflow)
- [Failure and safety semantics](#failure-and-safety-semantics)
- [Troubleshooting](#troubleshooting)

When run in a lab directory, freeze detects its single recognized topology
(`*.clab.yml`, `*.clab.yaml`, `clab.yml`, `clab.yaml`, `topology.yml`, or
`topology.yaml`) and writes `./<lab-directory-name>.tar.gz` by default. Pass
`-t` / `--topology` when running elsewhere or when the directory contains more
than one topology, and use `--output` to select another destination:

```bash
eclab freeze -t labs/demo/lab.clab.yml --output demo.tar.gz
```

Add `--offline` to create a strict offline bundle:

```bash
eclab freeze --offline
```

Offline archives contain a ready-to-run copy of the active eclab virtual
environment, the resolved Containerlab executable, the actual vrnetlab checkout,
and a Docker archive of non-vrnetlab topology images. Generated vrnetlab
appliance images and vendor VM inputs are not frozen: the recipient selects and
supplies the VM image they are entitled to use, and the bundled vrnetlab builds
it locally. The launcher selects only bundled tools and loads ordinary missing
images without a registry. Creation fails instead of producing an incomplete
archive when eclab is not running in a virtual environment, a required tool is
unavailable, or an ordinary topology image is absent from the local Docker
daemon. Pull ordinary lab images before freezing.

An offline bundle is platform-specific and still requires compatible host
facilities: Docker, Linux networking privileges, and QEMU/KVM where the lab
needs them. Licenses remain deliberately excluded and are supplied by the
recipient.

The archive contains a copied topology, a package lock and best-effort
wheelhouse, copied external VM images, and `run-eclab.sh`. Freeze first copies
the exact wheels used by locally installed eclab/Engulf packages, then obtains
remaining packages from the configured package index. It never includes license
files, pool paths, allocations, or clamp values. Pool-backed node licenses
become `__ECLAB_LICENSE_PROMPT__`, which asks the recipient for a license file,
pool directory, or `$VARIABLE` when the frozen lab is deployed.

Freeze copies the source lab while excluding managed state, virtual
environments, caches, known license files, legacy wrapper state, and the
current lab's `clab-<lab-name>` Containerlab runtime directory. Empty directories
left after exclusions are omitted. Add extra Git-ignore-style patterns to
`.eclab-freezeignore`; editions use `.<short-product>-freezeignore`. Symlinks
that point outside the source lab are rejected.

Archives made inside the lab directory are remembered in the lab's Engulf
workspace state. Later freezes exclude every still-present remembered archive,
so multiple share archives never get nested into each other. If an archive is
removed or no longer a regular file, its record is pruned automatically on the
next freeze. When `--output` already identifies a regular archive, an
interactive freeze asks whether to overwrite it; declining leaves it unchanged.

## Archive layout and provenance

Each archive has one sanitized root directory derived from the archive filename.
It includes:

| Entry | Purpose |
| --- | --- |
| Frozen lab files and topology | Source copy after built-in/custom exclusions, license redaction, and portable input rewriting. |
| `requirements.freeze.txt` | Exact installed wrapper, active plugin, and transitive package versions. |
| `wheelhouse/` | Best-effort exact/local and downloaded wheel set. It may be absent when no wheel was available. |
| `.eclab-freeze.env` | Non-secret Containerlab/vrnetlab repository and revision provenance when verifiable. |
| `run-eclab.sh` | Default deploy launcher that accepts alternate eclab arguments. |

The topology gains `x-eclab-freeze` format metadata recording format version,
application ID, package lock, tool provenance, license prompt policy, and
offline mode. Every node license value is replaced, and all `*_LIC_CLAMP`
entries are removed. Possible license files excluded by suffix are reported as
warnings.

Normal archives copy external configured vrnetlab source inputs into the staged
lab, rewrite the copied topology to relative inputs, and record their hashes.
Offline archives instead remove those inputs and expect the entitled recipient
to select the vendor VM source locally before the bundled builder runs.

## Recipient workflow

```bash
tar -xzf demo.tar.gz
cd demo
./run-eclab.sh
```

With no arguments, the launcher deploys the frozen topology. Arguments replace
that default, so `./run-eclab.sh inspect -t lab.clab.yml` and
`./run-eclab.sh destroy -t lab.clab.yml` use the same selected runtime.

A normal launcher first reuses a compatible installed eclab. An interactive
recipient may accept an incompatible installation or install the locked
packages; otherwise the script creates `.eclab-venv` and installs from the
wheelhouse/package index. Review the archive and package lock before executing
it: topologies, startup configs, scripts, Dockerfiles, and packages are
executable/privileged lab input.

An offline launcher uses only its copied Python environment and Containerlab,
disables checkout updates, points at the bundled vrnetlab checkout, and loads
the Docker archive only when a listed ordinary image is missing. It still calls
the host Docker daemon and needs compatible host privileges.

## Failure and safety semantics

The build occurs in a temporary directory next to the destination. The final
compressed archive is renamed into place only after staging, sanitization,
package collection, optional offline checks, and tar creation succeed. A failed
freeze does not leave a partial requested output.

The output must end in `.tar.gz` or `.tgz`, its parent must exist, and an
existing non-regular path or symlink is rejected. External symlinks in the lab
are rejected before copying; internal symlinks are preserved. Destroy a deployed
license-pool lab first—generated `.engulf-clab/licenses` copies make freeze fail
instead of risking inclusion.

## Troubleshooting

- If topology selection is ambiguous, pass `-t` explicitly.
- If overwrite fails non-interactively, choose a new output path or remove the
  existing regular archive intentionally; the command will not assume consent.
- Inspect warnings for omitted wheels or suspected license files. A normal
  archive can fall back to its package index, so it is not guaranteed offline.
- For `--offline` failures, run from the installed eclab virtual environment,
  make Containerlab/vrnetlab resolvable, and ensure every ordinary topology
  image exists locally before retrying.
- If a source symlink escapes, replace it with a copied lab-local input or an
  ignore rule; freeze will not dereference external content implicitly.
- If an old archive is unexpectedly excluded, remove it and freeze again; stale
  tracking records are pruned automatically.
