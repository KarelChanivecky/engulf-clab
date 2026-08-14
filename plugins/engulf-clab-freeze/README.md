# engulf-clab-freeze

Creates a shareable frozen lab without changing the source directory:

```bash
eclab freeze
```

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
environments, caches, known license files, legacy `.forticlab` state, and the
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
