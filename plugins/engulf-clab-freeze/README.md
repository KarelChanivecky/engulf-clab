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
