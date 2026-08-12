# engulf-clab

`engulf-clab` is a Python wrapper around [Containerlab](https://containerlab.dev/)
with an extensible, package-discovered plugin system. It keeps normal
Containerlab workflows intact while plugins can prepare images and host
resources, allocate licenses, rewrite a temporary topology, and verify the lab
after it starts.

The repository contains the wrapper application and independently publishable
plugin distributions. Install only the plugins a lab needs, or install the
meta-package to enable the complete maintained set.

## Quick start

Prerequisites are Python 3.14, Docker, and the privileges required by the
Containerlab features you choose. The ensure-containerlab plugin can provision
a Containerlab checkout and build its binary; installing Containerlab yourself
also works.

For a user-wide `eclab` command on `PATH`, use `pipx` (run
`pipx ensurepath` once after installing pipx):

```bash
pipx install engulf-clab
pipx inject engulf-clab engulf-clab-all-plugins
```

For a project-local installation, use a virtual environment:

```bash
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install engulf-clab engulf-clab-all-plugins

eclab deploy -t lab.clab.yml
eclab destroy -t lab.clab.yml

# Create a portable, sanitized copy for sharing.
eclab freeze -t lab.clab.yml --output lab-share.tar.gz
```

The ensure-containerlab plugin checks for `docker`. When a topology opts into
vrnetlab, ensure-vrnetlab also checks for `docker`, `qemu-img`, and
`qemu-system-x86_64` before deployment. Install the matching Docker and QEMU
packages for the host distribution, and ensure the invoking user can access the
Docker daemon.

For development directly from this checkout, install the wrapper and each
feature package you intend to exercise in editable mode:

```bash
python -m pip install -e ./engulf-clab
python -m pip install -e ./plugins/engulf-clab-ensure-containerlab
python -m pip install -e ./plugins/engulf-clab-health-gates
```

Alternatively, `install-dev.sh` builds the local Engulf and eclab trees into an
isolated development virtual environment. It requires a pointer to the Engulf
checkout:

```bash
ENGULF_DIR=../cliwrap ./install-dev.sh
source .venv/bin/activate
eclab --help
```

Use `./uninstall-dev.sh` to remove the development distributions from that
virtual environment without deleting the environment itself. Set `VENV_DIR` to
use a location other than `.venv`.

Engulf discovers installed plugin entry points automatically. `eclab`
passes ordinary arguments through to Containerlab. Wrapper diagnostic options
are removed before Containerlab runs; for example,
`--eclab-log-level INFO` enables informational logs and
`--eclab-plugin-log-level engulf_clab.wan=DEBUG` targets one
plugin.

## Typical topology

This example builds an image, allocates a license, waits for the resulting
nodes, and then deploys the normal Containerlab topology.

```yaml
name: demo

x-engulf-clab-health-gates:
  timeout: 180
  nodes: [router]

topology:
  nodes:
    router:
      image: example/router:dev
      uuid: 4c1a8ee8-6ef7-4501-bfc1-6b082c3120f0
      license: $ROUTER_LICENSES
      env:
        ECLAB_DOCKERFILE: router/Dockerfile
        ECLAB_DOCKER_CTX: router
  links: []
```

```bash
export ROUTER_LICENSES=$PWD/licenses
eclab deploy -t demo.clab.yml
```

See each plugin README for its exact YAML fields, environment variables,
required host tools, and cleanup behavior.

## Packages

| Package | Purpose |
| --- | --- |
| `engulf-clab` | Distribution that installs the `eclab` Containerlab wrapper command. |
| `engulf-clab-all-plugins` | Meta-package that installs all maintained plugins. |
| `engulf-clab-ensure-containerlab` | Finds, builds, or provisions Containerlab. |
| `engulf-clab-dockerfile-build` | Builds node images declared with Dockerfile variables. |
| `engulf-clab-ensure-vrnetlab` | Finds or provisions a vrnetlab checkout. |
| `engulf-clab-vrnetlab-build` | Builds vrnetlab node images. |
| `engulf-clab-license-pool` | Shares license files safely across labs. |
| `engulf-clab-freeze` | Produces sanitized, portable frozen lab archives. |
| `engulf-clab-wan` | Creates DHCP/NAT WAN bridges for marked nodes. |
| `engulf-clab-health-gates` | Waits for selected nodes to become ready. |
| `engulf-clab-lab-parser` | Shared original-topology and deferred-mutation API. |
| `engulf-clab-lab-writer` | Renders deferred mutations into a temporary topology. |

## Workspace and state

The canonical workspace is the directory containing the selected topology. A
topology supplied with `-t`, `--topo`, or `--topology` therefore keeps the same
workspace state even when the command is run from another directory. Calls
without a filesystem topology use the current directory.

Plugins use Engulf-managed user and workspace state plus leases for shared host
resources. Do not edit plugin state files while a deployment is running.

## Freezing a lab for sharing

`eclab freeze -t lab.clab.yml --output lab-share.tar.gz` leaves the source lab
unchanged and creates one sanitized archive. It contains the copied frozen
topology, exact Python package lock, best-effort wheelhouse, copied external VM
inputs, and `run-eclab.sh`. The launcher reuses a compatible installed `eclab`,
offers to use an incompatible one, or creates a lab-local virtual environment.

Frozen licenses become `__ECLAB_LICENSE_PROMPT__`; pool paths, allocations,
clamps, and license files are never included. The recipient supplies a file,
pool directory, or `$VARIABLE` interactively or through `ECLAB_LICENSE` /
`ECLAB_LICENSE_<NODE>`. Destroy an active lab before freezing it. Use
`.eclab-freezeignore` for extra Git-ignore-style exclusions; external symlinks
are rejected.

## Editions

An edition is a separately released launcher that reuses this application while
choosing a different command-facing name and plugin set. Environment-variable
prefixes derive from short product metadata, falling back to the full product
name: `eclab` uses `ECLAB_*`; an edition with short product name
`acme clab` uses `ACME_CLAB_*`.

```python
from engulf_clab import CONTAINERLAB_APPLICATION

ACME_CLAB = CONTAINERLAB_APPLICATION.edition(
    display_name="acme-clab",
    vendor="Acme Networks",
    short_product_name="acme clab",
    include_plugins={"com.example.acme.containerlab"},
)
```

## Contributing

Use Python 3.14 and the repository `.venv` when present. Keep changes focused
and run the narrowest relevant checks, such as unit tests, bytecode compilation,
plugin discovery, and `ruff check`.

Each plugin under `plugins/` is a self-contained distribution. A new plugin
needs its own `AGENTS.md`, MIT `LICENSE`, `pyproject.toml`, `src/` package, and
`py.typed` marker when typed. Plugins import `engulf_api` and
`engulf_executable_wrapper_api`, never the `engulf` runtime. Implement
side-effect-free `analyze_call()`; perform external work in `prepare_call()` or
`after_call()`; report through the callback logger; and use leases/state
transactions for shared resources.

Plugins publish both entry points with the exact plugin ID as the entry-point
name:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
engulf.plugins.v1.application.engulf_clab
```

## License

This monorepo and every plugin package are MIT licensed. Individual plugin
licenses carry `Copyright (c) 2026 Karel Chanivecky`.
