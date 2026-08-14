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
token and CA automatically. Set `ENGULF_DIR` when that checkout is not at
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

See each plugin README for its exact YAML fields, environment variables,
required host tools, and cleanup behavior.

## Packages

| Package | Purpose |
| --- | --- |
| `engulf-clab` | Distribution that installs the `eclab` Containerlab wrapper command. |
| `engulf-clab-mcp` | Local Unix-socket privileged MCP executor and standard-stdio bridge. |
| `engulf-clab-all-plugins` | Meta-package that installs all maintained plugins. |
| `engulf-clab-containers-api` | Typed contract for independently published container collections. |
| `engulf-clab-containers` | Injects active collection recipes into temporary topologies. |
| `engulf-clab-containers-core` | Core host connector, LDAP, proxy, and Firefox GUI collection. |
| `engulf-clab-ensure-containerlab` | Finds, builds, or provisions Containerlab. |
| `engulf-clab-dockerfile-build` | Builds node images declared with Dockerfile variables. |
| `engulf-clab-ensure-vrnetlab` | Finds or provisions a vrnetlab checkout. |
| `engulf-clab-vrnetlab-build` | Builds vrnetlab node images. |
| `engulf-clab-license-pool` | Shares license files safely across labs. |
| `engulf-clab-freeze` | Produces sanitized, portable frozen lab archives. |
| `engulf-clab-wan` | Creates DHCP/NAT WAN bridges for marked nodes. |
| `engulf-clab-lab-parser` | Shared original-topology and deferred-mutation API. |
| `engulf-clab-lab-writer` | Renders deferred mutations into a temporary topology. |

## Packaged containers

Active collection plugins provide reusable node images without copying their
Dockerfiles into each lab. List them with `eclab --eclab-containers-help`. A
collection owns the image namespace derived from its plugin ID; the core
`eclab.containers` collection provides `host-connector`, `ldap-389ds`,
`proxy-node`, and `ubuntu-firefox-gui`:

```yaml
topology:
  nodes:
    outside-vm:
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

The LDAP image serves 389 DS with Cockpit, the proxy image combines Squid,
Dante, and a control UI, and the Firefox image exposes an XFCE desktop through
noVNC. Their packaged recipes remain generic; labs provide addressing,
credentials, seeds, certificates, and proxy policy through topology fields.
See the core collection README for ports and environment variables.

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
clamps, and license files are never included. The recipient supplies a file,
pool directory, or `$VARIABLE` interactively or through `ECLAB_LICENSE` /
`ECLAB_LICENSE_<NODE>`. Destroy an active lab before freezing it. Use
`.eclab-freezeignore` for extra Git-ignore-style exclusions; external symlinks
are rejected. Containerlab's `clab-<lab-name>` runtime directory, managed
legacy state, and empty directories left after exclusions are omitted.

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

### Repository skill

The canonical `develop-eclab-lab` Codex skill lives under
`skills/develop-eclab-lab` and is also a separately buildable pip distribution.
Install a user-level copy and configure this checkout's hooks with:

```bash
make install-skill
```

The pip package embeds the skill and all copied Engulf/ECLAB context. After
installing `develop-eclab-lab`, run `develop-eclab-lab-install` to copy the
embedded skill into `~/.agents/skills/develop-eclab-lab`. The installed skill
does not need this checkout.

Run `make update-skill` after changing documentation copied into the skill, and
run `make check-skill` in CI. The hooks compare staged documentation with its
staged skill reference and reject vendor-specific material in the new skill.
Commits that change wrapper, plugin, or MCP behavior or documentation must
include exactly one review trailer:

```text
Skill-Impact: updated
```

or `Skill-Impact: none`. The `updated` value requires a staged change beneath
`skills/develop-eclab-lab/`.

## License

This monorepo and every plugin package are MIT licensed. Individual plugin
licenses carry `Copyright (c) 2026 Karel Chanivecky`.
