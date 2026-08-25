# engulf-clab

`engulf-clab` is a Python wrapper around [Containerlab](https://containerlab.dev/)
with an extensible, package-discovered plugin system. It keeps normal
Containerlab workflows intact while plugins can prepare images and host
resources, allocate licenses, rewrite a temporary topology, and verify the lab
after it starts.

The repository contains the wrapper application and independently publishable
plugin distributions. Install only the plugins a lab needs, or install the
meta-package to enable the complete maintained set.

## Contents

- [Documentation map](#documentation-map)
- [Quick start](#quick-start)
- [Topology language and runtime discovery](#topology-language-and-runtime-discovery)
- [Invocation lifecycle](#invocation-lifecycle)
- [Publishing](#publishing)
- [Local MCP control service](#local-mcp-control-service)
- [Typical topology](#typical-topology)
- [Packages](#packages)
- [Packaged containers](#packaged-containers)
- [Workspace and state](#workspace-and-state)
- [Freezing a lab for sharing](#freezing-a-lab-for-sharing)
- [Editions](#editions)
- [Contributing](#contributing)
- [License](#license)

## Documentation map

| Guide | Use it for |
| --- | --- |
| This README | Installation choices, package map, common topology patterns, workspace/state, editions, and releases |
| `engulf-clab/README.md` | Wrapper behavior, argument forwarding, plugin discovery, diagnostics, and library use |
| `plugins/*/USAGE.md` | Exact feature syntax, prerequisites, lifecycle, state, cleanup, and troubleshooting |
| `plugins/*/CONTRIBUTING.md` | Per-package role, architecture, invariants, and validation commands |
| `mcp-server/README.md` | Privileged local MCP architecture, configuration, tools, security boundary, and operations |
| `CONTRIBUTING.md` | Development setup, Engulf contracts, documentation standards, validation, commits, and releases |
| `skills/README.md` | Runtime-generated lab-skill architecture, installation, and contributor contract |

The nearest `AGENTS.md` adds non-user-facing invariants for agents changing a
specific package. Package source and tests remain the precise specification for
edge cases.

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
eclab install-completion  # Detect Bash, Zsh, or Fish from SHELL.

# Create a portable, sanitized copy for sharing.
eclab freeze
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

## Topology language and runtime discovery

Every topology remains a Containerlab YAML document. Use Containerlab's
authoritative
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json)
for standard keys such as `name`, `mgmt`, `topology`, `defaults`, `kinds`,
`nodes`, `links`, `kind`, `image`, `env`, `labels`, `startup-config`, and
`license`. eclab plugins consume conventions expressed through those valid
fields; they do not define a second topology language.

The installed launcher is the authority for its available features. Inspect it
before writing edition- or plugin-specific topology controls:

```bash
eclab --help
eclab --engulf-plugin-list
eclab --eclab-containers-help
```

`--help` appends one block for every active plugin that publishes help.
`--engulf-plugin-list` reports activation order, source distribution, and
version. The packaged-container command lists only collections discovered in
that environment. For an edition, run the edition launcher's commands instead;
an installation of base eclab does not prove that the edition declares the same
plugins.

`install-completion [bash|zsh|fish] [--output PATH]` installs completion for the
selected launcher. It prefers any registered native Containerlab completer; when
none exists, it sources the configured Containerlab executable's trusted
`completion <shell>` output once. Native and schema-declared plugin candidates are
then merged, while schema candidates remain available if native completion cannot be
loaded. Schema-backed wrapper flags provide per-invocation forms for most
process-level configuration variables. The environment variables remain supported
for persistent defaults, and CLI values win when both are present. Node `env` values
in topology YAML are unaffected.

Direct `containerlab` remains valid for labs that do not need wrapper features.
It cannot interpret eclab-managed WAN labels, allocate pooled licenses, prepare
packaged container recipes, build declared images, or create frozen archives.

## Invocation lifecycle

The wrapper preserves ordinary Containerlab arguments while Engulf coordinates
plugins around one call:

```text
CLI arguments
  -> schema-backed wrapper options are consumed into the invocation environment
  -> every plugin analyzes without side effects
  -> accepted plugins prepare resources and deferred topology mutations
  -> the writer materializes one temporary topology beside the source file
  -> Containerlab runs with the effective arguments
  -> plugins perform outcome-aware cleanup
```

Analysis failure prevents all preparation. The source topology is never
rewritten by the maintained mutation pipeline. Keeping the temporary topology
beside it preserves Containerlab's relative-path behavior, and the writer
removes the temporary file after the wrapped call.

Plugin dependencies establish correctness-sensitive ordering. In a complete
installation, collections register recipes before the manager injects them;
the parser publishes the immutable topology before mutators run; ensure plugins
prepare tool sources before builders; and the writer runs after all mutators.
Use the live plugin list rather than relying on a hard-coded sequence when
debugging another edition or package set.

## Publishing

Publish every distribution in this monorepo to a PyPI-compatible repository by
setting its explicit upload endpoint:

```bash
export TWINE_REPOSITORY_URL=https://packages.example.test/
./publish.sh
```

The publisher removes and rebuilds the root `dist/` tree, validates every wheel
and source distribution with Twine, and uploads only those fresh artifacts. If
the URL matches the package repository managed by the neighboring Engulf
checkout, it verifies that the managed container is active and loads its upload
token and CA automatically. The publish target explicitly checks that both the
`engulf-clab-develop-eclab-lab` wheel and source distribution are present before uploading.
Set `ENGULF_DIR` when that checkout is not at
`../engulf`; credentials for other repositories use Twine's normal environment
variables or configuration.

## Local MCP control service

`engulf-clab-mcp` is an optional local control plane for MCP agents that need to
deploy and destroy labs without a general-purpose `sudo` path. An unprivileged
`eclab-mcp` bridge uses standard MCP stdio and sends narrowly typed requests to
a root-owned `eclab-mcpd` daemon over a group-protected Unix socket. It exposes
lab discovery, validation, deploy/destroy jobs, status, node logs, diagnostics,
and job controls—never arbitrary commands, arbitrary flags, arbitrary paths, or
`destroy --all`.

From a source checkout, one guided command installs the root-owned service
runtime, creates the local-only service, and collects the initial configuration:

```bash
ENGULF_DIR=../engulf ./install-mcp.sh
```

It asks for allowed topology roots, the local users allowed to operate labs, and
optional service-owned profile variables (with a hidden prompt for secrets).
It then validates the generated configuration and starts the service. Docker,
Containerlab, and Python 3.14 must already be available on the host.

For an unattended installation, provide the trusted root and operator directly:

```bash
ENGULF_DIR=../engulf ./install-mcp.sh --noninteractive \
  --lab-root labs=/srv/eclab-labs \
  --user "$USER"
```

After publishing the packages, install the service runtime in an
administrator-owned environment and use the same guided service installer:

```bash
sudo python3.14 -m venv /opt/eclab-mcp/venv
sudo /opt/eclab-mcp/venv/bin/python -m pip install 'engulf-clab-mcp[all-plugins]'
sudo /opt/eclab-mcp/venv/bin/eclab-mcp-install-system --interactive
```

Or pass the configuration explicitly:

```bash
sudo /opt/eclab-mcp/venv/bin/eclab-mcp-install-system \
  --lab-root labs=/srv/eclab-labs \
  --user "$USER"
```

See [the MCP server guide](mcp-server/README.md) for its root-owned TOML
configuration, client setup, environment override boundary, and uninstall
procedure. Members of the `eclab-mcp` group are trusted lab operators; a
writable configured lab root is privileged input. The guided source installer
uses `/opt/eclab-mcp/venv`, not this user-writable development virtual
environment.

Engulf discovers installed plugin entry points automatically. `eclab`
passes ordinary arguments through to Containerlab. Wrapper diagnostic options
are removed before Containerlab runs; for example,
`--eclab-log-level INFO` enables informational logs and
`--eclab-plugin-log-level engulf_clab.wan=DEBUG` targets one
plugin.

## Typical topology

This example builds an image, allocates a license, and then deploys the normal
Containerlab topology.

```yaml
name: demo

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

See each plugin `USAGE.md` for its exact YAML fields, environment variables,
required host tools, and cleanup behavior.

## Packages

| Package | Plugin ID / command | Purpose |
| --- | --- | --- |
| `engulf-clab` | `eclab` | Distribution that installs the Containerlab wrapper command. |
| `engulf-clab-mcp` | `eclab-mcp`, `eclab-mcpd` | Local Unix-socket privileged MCP executor and standard-stdio bridge. |
| `engulf-clab-all-plugins` | None | Meta-package that installs all maintained plugins. |
| `engulf-clab-containers-api` | Contract only | Typed contract for independently published container collections. |
| `engulf-clab-containers` | `engulf_clab.containers` | Injects active collection recipes into temporary topologies. |
| `engulf-clab-containers-core` | `eclab.containers` | Core host-connector collection. |
| `engulf-clab-ensure-checkout` | Library only | Shared safe Git checkout provisioning and update logic. |
| `engulf-clab-ensure-containerlab` | `engulf_clab.ensure_containerlab` | Finds, builds, or provisions Containerlab. |
| `engulf-clab-dockerfile-build` | `engulf_clab.dockerfile_build` | Builds node images declared with Dockerfile variables. |
| `engulf-clab-ensure-vrnetlab` | `engulf_clab.ensure_vrnetlab` | Finds or provisions a vrnetlab checkout. |
| `engulf-clab-vrnetlab-build` | `engulf_clab.vrnetlab_build` | Builds vrnetlab node images. |
| `engulf-clab-license-pool` | `engulf_clab.license_pool` | Shares license files safely across labs. |
| `engulf-clab-freeze` | `engulf_clab.freeze` | Produces sanitized, portable frozen lab archives. |
| `engulf-clab-wan` | `engulf_clab.wan` | Creates DHCP/NAT WAN bridges for marked nodes. |
| `engulf-clab-lab-parser` | `engulf_clab.lab_parser` | Shared original-topology and deferred-mutation API. |
| `engulf-clab-lab-writer` | `engulf_clab.lab_writer` | Renders deferred mutations into a temporary topology. |

## Packaged containers

Active collection plugins provide reusable node images without copying their
Dockerfiles into each lab. List them with `eclab --eclab-containers-help`. A
collection owns the image namespace derived from its plugin ID; the core
`eclab.containers` collection provides `host-connector`:

```yaml
topology:
  nodes:
    outside-vm:
      kind: linux
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
  links:
    - endpoints: ["router:eth1", "outside-vm:eth1"]
```

The connector reserves `eth0` for Containerlab management and treats every
other interface as lab-facing. It forwards all IPv4 or IPv6 protocols from each
VIP to its external target and source-NATs through `eth0`; it does not provide
DHCP, a general WAN, or an SSH service of its own. Use the unnumbered variable
or `_0` (not both), followed by sparse numbered variables.

The host connector's packaged guide describes its interface mappings, required
capabilities, packet flow, and troubleshooting. Labs provide addressing and
routes through normal topology fields.

## Workspace and state

The canonical workspace is the directory containing the selected topology. A
topology supplied with `-t`, `--topo`, or `--topology` therefore keeps the same
workspace state even when the command is run from another directory. Calls
without a filesystem topology use the current directory.

Plugins use Engulf-managed user and workspace state plus leases for shared host
resources. Do not edit plugin state files while a deployment is running.

## Freezing a lab for sharing

`eclab freeze` leaves the source lab
unchanged and creates one sanitized archive. It contains the copied frozen
topology, exact Python package lock, best-effort wheelhouse, copied external VM
inputs, and `run-eclab.sh`. The launcher reuses a compatible installed `eclab`,
offers to use an incompatible one, or creates a lab-local virtual environment.
With `--offline`, freeze instead includes the active installed eclab virtual
environment, the resolved Containerlab executable, the actual vrnetlab checkout,
and non-vrnetlab topology images currently in Docker. It does not bundle
generated appliance images or vendor VM inputs;
the recipient supplies their selected VM image. The offline launcher uses only
the bundled runtime and tools and loads ordinary absent images from the archive.
Freeze fails if a required component is unavailable. Offline archives remain
platform-specific and require compatible Docker and host networking/QEMU facilities.

When no topology option is supplied, freeze selects the one recognized topology
in the current directory and writes `<lab-directory-name>.tar.gz` there. Pass
`-t`, `--topo`, or `--topology` to select a lab from another directory or to
disambiguate multiple topology files, or `--output ARCHIVE` for a custom
destination. When an existing regular archive is selected, freeze asks whether
to overwrite it; declining leaves the existing archive unchanged.

Every archive previously produced inside a lab is recorded in that lab's Engulf
workspace state. Subsequent freezes exclude the still-present recorded archives,
preventing nested archives and unbounded source growth. Records for paths that
have been removed or are no longer regular files are pruned automatically.

Frozen licenses become `__ECLAB_LICENSE_PROMPT__`; pool paths, allocations,
clamps, and license files are never included. `ECLAB` is a fixed label
prefix, the same across every edition. The recipient supplies a file, pool
directory, or `$VARIABLE` interactively or through `ECLAB_LICENSE` /
`ECLAB_LICENSE_<NODE>`. Destroy an active lab before freezing it. Use
`.<state-prefix-lowercase>-freezeignore` for extra Git-ignore-style
exclusions; external symlinks are rejected. The active application's
`.<state-prefix-lowercase>` lab state (namespaced by short product name and kept
separate from the fixed label prefix),
Containerlab's `clab-<lab-name>` runtime directory, and empty directories left
after exclusions are omitted.

## Editions

An edition is a separately released launcher that reuses this application while
choosing a different command-facing name and plugin set.

Topology label and environment-variable prefixes are fixed to `ECLAB_*` for
every edition — plugins never derive them from product metadata. A label
written for one edition works unchanged under any other, so users are not
confused by near-identical prefixes (`ECLAB_*` versus something
edition-specific) that mean the same thing.

`short_product_name` is not used for those portable topology keys. It names
topology-local state and the runtime schema pipeline. A launcher that only
changes branding may keep `"eclab"` and share base state and schema. A distinct
superset executable with its own generated skill uses a unique lowercase
hyphen-normalized value, registers a schema pipeline with `eclab` as its parent,
and therefore receives separate topology-local state and schema artifacts.
`display_name`, `vendor`, and `product` remain its command-facing branding:

```python
from engulf_clab import CONTAINERLAB_APPLICATION

ACME_CLAB = CONTAINERLAB_APPLICATION.edition(
    display_name="acme-clab",
    vendor="Acme Networks",
    product="Acme Containerlab",
    short_product_name="acme-clab",
    include_plugins={"com.example.acme.containerlab"},
)
```

The edition's collector requests only `acme-clab`; base eclab declarations are
inherited and expanded against the running edition metadata. The bundled
`engulf-clab-develop-eclab-lab` collector remains exclusive to eclab, so the
edition owns its own skill command, renderer, target, and refresh tracking.

## Contributing

Use Python 3.14 and the repository `.venv` when present. Keep changes focused
and run the narrowest relevant checks, such as unit tests, bytecode compilation,
plugin discovery, and `ruff check`.

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the complete development setup,
plugin lifecycle contract, package checklist, documentation requirements,
validation matrix, commit policy, and release workflow.

Each plugin under `plugins/` is a self-contained distribution. A new plugin
needs its own concise `README.md`, complete `USAGE.md`, contributor-oriented
`CONTRIBUTING.md`, `AGENTS.md`, MIT `LICENSE`, `pyproject.toml`, `src/` package,
and `py.typed` marker when typed. Plugins import `engulf_api` and
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

### Runtime-generated skill

Each installed plugin declares its exact controls and packaged references. The
schema generator emits a task catalog and compact YAML capability file for each
plugin, while also combining the declarations with the selected Containerlab
source's `schemas/clab.schema.json` for complete validation.
`engulf-clab-develop-eclab-lab` installs the base result as the static,
fingerprinted `develop-eclab-lab` Codex skill. Read
[`skills/README.md`](skills/README.md) for the contract and lifecycle.

For the standard edition, install it into a Codex configuration root with:

```bash
eclab install-develop-eclab-lab-skill "$CODEX_HOME"
```

Superset editions declare and request their own inherited schema pipeline,
consume the resulting bundle, and own a separate skill package. The eclab
installer refuses unsafe or unrelated destinations and refreshes only its
tracked eclab installations after later runtime schema changes. Run `make
check-skill` in CI.
Commits that change wrapper, plugin, or MCP behavior or documentation must
include exactly one review trailer:

```text
Skill-Impact: updated
```

or `Skill-Impact: none`.

## License

This monorepo and every plugin package are MIT licensed. Individual plugin
licenses carry `Copyright (c) 2026 Karel Chanivecky`.
