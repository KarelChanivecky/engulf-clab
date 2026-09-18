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

- [Complete feature inventory](#complete-feature-inventory)
- [Documentation map](#documentation-map)
- [Quick start](#quick-start)
- [Topology language and runtime discovery](#topology-language-and-runtime-discovery)
- [Invocation lifecycle](#invocation-lifecycle)
- [Reusable image providers](#reusable-image-providers)
- [Local MCP control service](#local-mcp-control-service)
- [Typical topology](#typical-topology)
- [Packages](#packages)
- [Packaged containers](#packaged-containers)
- [Workspace and state](#workspace-and-state)
- [Freezing a lab for sharing](#freezing-a-lab-for-sharing)
- [Editions](#editions)
- [Contributing](#contributing)
- [License](#license)

## Complete feature inventory

Every cell below is an implemented capability around which a meaningful user
story can be written. Ordinary Containerlab behavior, internal implementation
mechanisms, correctness guarantees, and package metadata are intentionally not
repeated. The installed launcher's help and plugin list remain authoritative
for a particular environment or edition.

| Feature | Feature |
| --- | --- |
| [Automatically provision Containerlab][clab-resolution] | [Automatically provision vrnetlab][vrnet-checkout] |
| [Select a custom Containerlab executable or checkout][clab-resolution] | [Pin or update the Containerlab version][clab-checkout] |
| [Select a custom vrnetlab checkout][vrnet-checkout] | [Pin or update the vrnetlab version][vrnet-checkout] |
| [Build Containerlab automatically from source][clab-checkout] | [Configure sudo-less Containerlab access][clab-sudoless] |
| [Install Bash, Zsh, or Fish completion][wrapper-completion] | [Inspect installed plugin features and versions][wrapper-plugins] |
| [Configure global or per-plugin diagnostics][wrapper-diagnostics] | [Load topology variables from a lab-local environment file][parser-env] |
| [Install only the eclab feature packages a lab needs][all-plugins] | [Create a separately branded eclab edition][wrapper-editions] |
| [Build node images from topology-declared Dockerfiles][dockerfile-config] | [Choose per-node Docker build contexts and arguments][dockerfile-config] |
| [Automatically build Dockerfile base-image dependencies][image-core] | [Build independent container images in parallel][image-core] |
| [Build base images without deploying their builder nodes][dockerfile-build] | [Reuse locally available images without pulling][image-core] |
| [Provision Docker images from `.tar` archives][archive-config] | [Provision Docker images from gzip-, bzip2-, or xz-compressed `docker save` archives][archive-config] |
| [Select and retag an image from a multi-image archive][archive-behavior] | [Reload an updated archive that uses an existing tag][archive-behavior] |
| [Automatically build vrnetlab images][vrnet-build] | [Build vrnetlab images from raw `.qcow2` files][vrnet-build] |
| [Build vrnetlab images from compressed VM archives][vrnet-build] | [Select default or per-node VM image sources][vrnet-sources] |
| [Configure parallel vrnetlab build jobs][vrnet-build] | [Reuse a matching completed vrnetlab build][vrnet-lifecycle] |
| [Use package-provided helper containers][containers-use] | [List helper containers available in the current installation][containers-use] |
| [Map IPv4 or IPv6 lab VIPs to external hosts][core-host] | [Give a lab node outbound access through a NAT container][core-wan] |
| [Provide DHCP from a WAN-access container][core-wan] | [Build PKI-aware application containers from Debian or Fedora bases][pki-bases] |
| [Allocate node licenses from shared directory pools][license-inputs] | [Keep the same pooled license for a stable node identity][license-lifecycle] |
| [Select pooled licenses by sticky, round-robin, or least-recently-used policy][license-strategy] | [Clamp a node to a specific license file][license-inputs] |
| [Resolve redacted licenses when deploying a defrosted lab][license-frozen] | [Share license pools safely across concurrently managed labs][license-lifecycle] |
| [Assign stable IPv4 management addresses][sticky-config] | [Assign stable IPv6 management addresses][sticky-config] |
| [Configure private management-address pools and exclusions][sticky-config] | [Preserve node addresses as a lab topology changes][sticky-lifecycle] |
| [Preserve a complete explicitly addressed management network][sticky-explicit] | [Retain a lab's management network across redeploys][sticky-lifecycle] |
| [Add a managed DHCP WAN bridge to a topology][wan-config] | [Give isolated lab nodes managed outbound IPv4 NAT][wan-config] |
| [Configure WAN subnet, gateway, DHCP pool, DNS, and lease time][wan-config] | [Select the host uplink used by a managed WAN][wan-config] |
| [Share a compatible managed WAN bridge between labs][wan-lifecycle] | [Create local and global PKI catalogs][pki-catalog] |
| [Create root and intermediate certificate authorities][pki-catalog] | [Create server and client certificates][pki-catalog] |
| [Create cross-signed CA variants][pki-catalog] | [Create reusable certificate profiles][pki-catalog] |
| [Generate RSA or ECDSA keys][pki-catalog] | [Generate Ed25519 or Ed448 keys][pki-catalog] |
| [Generate ML-DSA keys when supported by the cryptography provider][pki-catalog] | [Configure certificate subjects and validity periods][pki-catalog] |
| [Add DNS, IP, email, or URI subject alternative names][pki-catalog] | [Configure certificate key usage and extended key usage][pki-catalog] |
| [Configure CA path-length and name constraints][pki-catalog] | [Configure AIA and OCSP responder URLs][pki-catalog] |
| [Configure CRL distribution-point URLs][pki-catalog] | [Configure certificate policies and CPS URLs][pki-catalog] |
| [Add custom certificate extensions][pki-catalog] | [Export certificates as PEM, DER, PKCS#12, or JKS][pki-catalog] |
| [Choose which CAs a node trusts][pki-trust] | [Give selected nodes access to designated private CAs][pki-catalog] |
| [Give each node only its requested certificates and keys][pki-trust] | [Choose a custom in-container PKI mount location][pki-catalog] |
| [Initialize, edit, and validate the global PKI catalog][pki-lifecycle] | [Inspect the effective PKI catalog and node requests without generating keys][pki-lifecycle] |
| [Add declared PKI service containers to a lab][pki-trust] | [Install projected trust into Linux system trust stores][linux-pki] |
| [Choose augmented or isolated application trust][linux-pki] | [Install projected trust into Chrome and Chromium profiles][linux-pki] |
| [Install projected trust into a managed Firefox profile][linux-pki] | [Select browser client certificates][linux-pki] |
| [Generate Playwright client-certificate configuration][linux-pki] | [Configure a client identity for curl][linux-pki] |
| [Generate an nginx TLS identity fragment][linux-pki] | [Inject authorized CA certificates into FortiGate nodes][fgt-pki] |
| [Inject authorized local certificates and keys into FortiGate nodes][fgt-pki] | [Package a lab for sharing with `freeze`][freeze-archive] |
| [Restore a packaged lab with `defrost`][freeze-expand] | [Create a sanitized archive without credentials or license files][freeze-sanitize] |
| [Reproduce the Python package versions recorded by a frozen lab][freeze-bundles] | [Include topology-referenced external VM inputs][freeze-bundles] |
| [Create an offline package with eclab and Containerlab][freeze-bundles] | [Include the selected vrnetlab checkout in an offline package][freeze-bundles] |
| [Include ordinary Docker images in an offline package][freeze-bundles] | [Run a frozen lab from its self-contained launcher][freeze-archive] |
| [Redact licenses during freeze and resolve them during defrost][freeze-sanitize] | [Exclude additional files with a lab-specific freeze-ignore file][freeze-sanitize] |
| [Choose a custom freeze archive destination][freeze-archive] | [Export explicitly allowed PKI secrets with passphrase encryption][pki-lifecycle] |
| [Inspect CPU and RAM consumption for one or all known labs][consumption] | [Inspect lab-directory and Docker-image storage consumption][consumption] |
| [Compare unique and shared image storage by lab][consumption] | [Poll live lab resource consumption][consumption] |
| [Distinguish deployed, stopped, and reclaimed labs][consumption] | [Reclaim Docker storage for one lab][reclaim] |
| [Destroy one lab and reclaim its Docker resources][reclaim] | [Destroy every lab and reclaim with `destroy --all --reclaim`][reclaim] |
| [Reclaim every known lab after all labs are destroyed][reclaim] | [Reclaim only labs whose containers are stopped][reclaim] |
| [Remove lab containers, writable layers, and anonymous volumes][reclaim] | [Remove Docker images used exclusively by reclaimed labs][reclaim] |
| [Report the amount of Docker storage reclaimed][reclaim] | [Generate a topology schema for the installed eclab feature set][schema] |
| [Validate against the exact selected Containerlab schema][schema-source] | [Browse documentation for detected Containerlab node kinds][schema-source] |
| [Browse matching vrnetlab builder documentation][schema-source] | [Generate a task-routed catalog of installed eclab capabilities][schema] |
| [Install a Codex lab-development skill matching the active runtime][skill] | [Refresh generated lab guidance after installed features change][skill] |
| [Keep a static comparison skill beside the generated skill][static-skill] | [Install a comprehensive demonstration lab][demo] |
| [Discover labs approved for MCP operation][mcp-tools] | [Validate an approved lab through MCP before running it][mcp-tools] |
| [Deploy or destroy an approved lab through MCP][mcp-tools] | [Inspect normalized lab and node status through MCP][mcp-tools] |
| [Retrieve bounded node logs through MCP][mcp-tools] | [Inspect eclab, Containerlab, and Docker diagnostics through MCP][mcp-tools] |
| [Monitor asynchronous MCP lifecycle jobs][mcp-jobs] | [Retrieve logs for an MCP lifecycle job][mcp-jobs] |
| [Cancel an MCP lifecycle job][mcp-jobs] | [Use administrator-defined MCP runtime profiles][mcp-profiles] |
| [Publish a reusable packaged-container collection][containers-author] | [Publish an application-neutral Docker image provider][image-api] |
| [Extend freeze and defrost with an independent plugin][freeze-api] | [Consume typed PKI projections from an independent integration][pki-api] |
| [Build tools against the typed lab-registry API][registry-api] | [Add controls to an edition-aware runtime schema pipeline][schema-api] |

[clab-resolution]: plugins/engulf-clab-ensure-containerlab/USAGE.md#resolution
[clab-checkout]: plugins/engulf-clab-ensure-containerlab/USAGE.md#managed-checkout
[clab-sudoless]: plugins/engulf-clab-ensure-containerlab/USAGE.md#sudo-less-operation
[vrnet-checkout]: plugins/engulf-clab-ensure-vrnetlab/USAGE.md#checkout-selection
[wrapper-completion]: engulf-clab/README.md#shell-completion
[wrapper-plugins]: engulf-clab/README.md#plugin-discovery
[wrapper-diagnostics]: engulf-clab/README.md#diagnostics-and-workspace-identity
[parser-env]: plugins/engulf-clab-lab-parser/USAGE.md#lab-environment-file
[all-plugins]: plugins/engulf-clab-all-plugins/README.md#included-distributions
[wrapper-editions]: engulf-clab/README.md#editions
[dockerfile-config]: plugins/engulf-clab-dockerfile-build/USAGE.md#configuration
[dockerfile-build]: plugins/engulf-clab-dockerfile-build/USAGE.md#build-behavior
[image-core]: plugins/engulf-docker-image-core/USAGE.md
[archive-config]: plugins/engulf-clab-image-archive/USAGE.md#configuration
[archive-behavior]: plugins/engulf-clab-image-archive/USAGE.md#provisioning-behavior
[vrnet-build]: plugins/engulf-clab-vrnetlab-build/USAGE.md#node-and-source-configuration
[vrnet-sources]: plugins/engulf-clab-vrnetlab-build/USAGE.md#source-precedence
[vrnet-lifecycle]: plugins/engulf-clab-vrnetlab-build/USAGE.md#validation-and-build-lifecycle
[containers-use]: plugins/engulf-clab-containers/USAGE.md#topology-use
[core-host]: plugins/engulf-clab-containers-core/USAGE.md#host-connector
[core-wan]: plugins/engulf-clab-containers-core/USAGE.md#wan-access
[pki-bases]: plugins/engulf-clab-containers-pki/USAGE.md#inherit-a-base
[license-inputs]: plugins/engulf-clab-license-pool/USAGE.md#inputs
[license-strategy]: plugins/engulf-clab-license-pool/USAGE.md#selection-strategies
[license-lifecycle]: plugins/engulf-clab-license-pool/USAGE.md#allocation-lifecycle
[license-frozen]: plugins/engulf-clab-license-pool/USAGE.md#frozen-prompts-and-security
[sticky-config]: plugins/engulf-clab-sticky-ip/USAGE.md#allocation-configuration
[sticky-explicit]: plugins/engulf-clab-sticky-ip/USAGE.md#explicit-addressing
[sticky-lifecycle]: plugins/engulf-clab-sticky-ip/USAGE.md#availability-and-lifecycle
[wan-config]: plugins/engulf-clab-wan/USAGE.md#configuration
[wan-lifecycle]: plugins/engulf-clab-wan/USAGE.md#host-changes-and-cleanup
[pki-catalog]: plugins/engulf-clab-pki/USAGE.md#catalog-and-node-requests
[pki-trust]: plugins/engulf-clab-pki/USAGE.md#trust-and-inventory
[pki-lifecycle]: plugins/engulf-clab-pki/USAGE.md#lifecycle-state-and-security
[linux-pki]: plugins/engulf-clab-pki-linux-core/USAGE.md
[fgt-pki]: plugins/engulf-clab-vrnetlab-fortigate-pki-injector/USAGE.md#generated-launcher-environment
[freeze-bundles]: plugins/engulf-clab-freeze/USAGE.md#normal-and-offline-bundles
[freeze-sanitize]: plugins/engulf-clab-freeze/USAGE.md#sanitization-and-exclusions
[freeze-archive]: plugins/engulf-clab-freeze/USAGE.md#archive-and-recipient-workflow
[freeze-expand]: plugins/engulf-clab-freeze/USAGE.md#expanding-an-archive
[consumption]: plugins/engulf-clab-consumption/USAGE.md
[reclaim]: plugins/engulf-clab-reclaim/USAGE.md
[schema]: plugins/engulf-clab-schema/USAGE.md
[schema-source]: plugins/engulf-clab-schema/USAGE.md#source-identity
[skill]: plugins/engulf-clab-develop-eclab-lab/USAGE.md
[static-skill]: skills/README.md#static-comparison-baseline
[demo]: demo-lab/README.md
[mcp-tools]: mcp-server/README.md#mcp-tools
[mcp-jobs]: mcp-server/README.md#jobs-and-cancellation
[mcp-profiles]: mcp-server/README.md#configure-lab-roots-and-profiles
[containers-author]: plugins/engulf-clab-containers-api/README.md#publishing-a-collection
[image-api]: plugins/engulf-docker-image-api/USAGE.md
[freeze-api]: plugins/engulf-clab-freeze-api/USAGE.md
[pki-api]: plugins/engulf-clab-pki-api/USAGE.md
[registry-api]: plugins/engulf-clab-lab-registry-api/USAGE.md
[schema-api]: plugins/engulf-clab-schema-api/README.md#edition-schema-pipelines

## Documentation map

| Guide | Use it for |
| --- | --- |
| This README | Installation choices, package map, common topology patterns, workspace/state, and editions |
| `engulf-clab/README.md` | Wrapper behavior, argument forwarding, plugin discovery, diagnostics, and library use |
| `plugins/*/USAGE.md` | Exact feature syntax, prerequisites, lifecycle, state, cleanup, and troubleshooting |
| `plugins/*/CONTRIBUTING.md` | Per-package role, architecture, invariants, and validation commands |
| `mcp-server/README.md` | Privileged local MCP architecture, configuration, tools, security boundary, and operations |
| `CONTRIBUTING.md` | Development setup, Engulf contracts, documentation standards, validation, commits, and releases |
| `skills/README.md` | Runtime-generated lab-skill architecture, installation, and contributor contract |
| [Planned features](planned-features/) | Proposed capabilities and acceptance criteria for future implementation |

The nearest `AGENTS.md` adds non-user-facing invariants for agents changing a
specific package. Package source and tests remain the precise specification for
edge cases.

## Quick start

**Requires Python 3.12 or newer.** On an older interpreter `pip` reports
`No matching distribution found for engulf-clab`, which reads as though the
package does not exist; check `python3 --version` first, and install with an
explicit `python3.12 -m pip` when it is not your default.

Other prerequisites are Docker and the privileges required by the
Containerlab features you choose. `eclab` itself must run unprivileged: the
shared goal has no Engulf privilege opt-in, so an elevated launch (root or
Windows administrator) is refused at startup with framework exit code 70
rather than loading plugins as root. The ensure-containerlab plugin can
provision a Containerlab checkout and build its binary; installing Containerlab
yourself also works.

For a user-wide `eclab` command on `PATH`, use `pipx` (run
`pipx ensurepath` once after installing pipx):

```bash
pipx install engulf-clab
pipx inject engulf-clab engulf-clab-all-plugins
```

For a project-local installation, use a virtual environment:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install engulf-clab engulf-clab-all-plugins

eclab deploy -t lab.clab.yml
eclab destroy -t lab.clab.yml
eclab install-completion  # Detect Bash, Zsh, or Fish from SHELL.

# Create a portable, sanitized copy for sharing, and expand a received one.
eclab freeze
eclab defrost shared-lab.tar.gz
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

`make` owns the development environment. It creates `.venv` and builds every
local distribution into `dist/`:

```bash
make environment
make build
```

Use `make build-<package>` for a single distribution, where `<package>` is the
distribution name from the `PACKAGES` list in the `Makefile`. Remove `.venv` to
reset the development environment.

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
  -> accepted plugins prepare resources, graph fragments, and deferred topology mutations
  -> image providers resolve recursively and selected build/pull recipes run dependency-first
  -> provisioned roots are marked image-pull-policy Never in the derived topology
  -> the writer materializes one temporary topology beside the source file
  -> Containerlab runs with the effective arguments
  -> plugins perform outcome-aware cleanup
```

Analysis failure prevents all preparation. The source topology is never
rewritten by the maintained mutation pipeline. Keeping the temporary topology
beside it preserves Containerlab's relative-path behavior, and the writer
removes the temporary file after the wrapped call.

Plugin dependencies establish correctness-sensitive ordering. In a complete
installation, collections register before the manager exposes their image
provider; the parser publishes the immutable topology before mutators run;
Dockerfile adapters contribute graph fragments before the image dispatcher;
ensure plugins prepare tool sources before builders; and the writer runs after
all mutators and image resolution.
Use the live plugin list rather than relying on a hard-coded sequence when
debugging another edition or package set.

## Reusable image providers

Docker image resolution is not tied to eclab or YAML. The
`engulf-docker-image-api` distribution defines immutable roots, recipes,
parameters, provider responses, context registries, and the
`org.engulf.docker-image` goal plugin contract. `engulf-docker-image-core`
provides Dockerfile `FROM` analysis, authority-ranked provider selection with
execution fallback, a low-authority pull provisioner, and dependency-first
execution:

```text
application-owned parser -> ImageBuildGraph -> provider dispatcher
                                             -> dependency requirement -> providers again
                                             <- selected recipes on backtracking
                                             -> Docker builds/pulls, dependencies first
```

An application can parse JSON, YAML, value files, or programmatic input and
inject only a graph loader into `DockerImageGoal`. Providers publish against
that neutral goal catalog. eclab instead uses a thin executable-wrapper adapter:
final node `image` values become roots, node-local custom parameters remain
ordinary node `env` entries, Dockerfile nodes contribute graph fragments, and packaged
containers register providers. The Dockerfile and container plugins import
neither one another nor one another's IDs; both depend only on the neutral
contract and `engulf_clab.image_build` dispatcher.

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
Containerlab, and Python 3.12 or newer must already be available on the host.

For an unattended installation, provide the trusted root and operator directly:

```bash
ENGULF_DIR=../engulf ./install-mcp.sh --noninteractive \
  --lab-root labs=/srv/eclab-labs \
  --user "$USER"
```

After publishing the packages, install the service runtime in an
administrator-owned environment and use the same guided service installer:

```bash
sudo python3.12 -m venv /opt/eclab-mcp/venv
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
    router-base-build:
      image: example/router-base:dev
      env:
        ECLAB_DOCKERFILE: router-base/Dockerfile
        ECLAB_DOCKER_CTX: router-base
        ECLAB_DOCKER_BASE_NODE: "true"
    router:
      image: example/router:dev
      uuid: 4c1a8ee8-6ef7-4501-bfc1-6b082c3120f0
      license: $ROUTER_LICENSES
      env:
        ECLAB_DOCKERFILE: router/Dockerfile
        ECLAB_DOCKER_CTX: router
  links: []
```

Here `router-base-build` is an explicit image-build root but is removed from the
derived topology before Containerlab runs. A normal `FROM
example/router-base:dev` in `router/Dockerfile` connects the recipes; each node
keeps its own context, build arguments, and Docker flags.

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
| `engulf-clab-demo-lab` | `eclab-demo-lab-install` | Non-plugin installer for one comprehensive client/Fake-WAN/FortiGate/DMZ/work demonstration lab. |
| `engulf-clab-develop-eclab-lab` | `eclab install-develop-eclab-lab-skill` | Runtime-generated eclab skill collector. |
| `engulf-clab-develop-eclab-lab-static` | `develop-eclab-lab-static-install` | Historical static skill retained for comparative evaluation. |
| `engulf-clab-schema-api` | Contract only | Typed runtime control, reference, task-routing, and edition-pipeline declaration API. |
| `engulf-clab-schema` | `engulf_clab.schema` | Compiles active declarations with exact Containerlab/vrnetlab sources into catalogs, provider references, and validation schemas. |
| `engulf-docker-image-api` | Contract only | Application-neutral image graph, parameter, provider, and Engulf goal-plugin contracts. |
| `engulf-docker-image-core` | Library/goal | Recursive Dockerfile dependency resolution, provider backtracking, and dependency-first builds. |
| `engulf-host-exec` | Library only | Sudo-aware host and Docker child commands with caller configuration and unprivileged Make builds. |
| `engulf-clab-containers-api` | Contract only | Typed contract for independently published container collections. |
| `engulf-clab-containers` | `engulf_clab.containers` | Injects collection runtime fields and registers the collection image provider. |
| `engulf-clab-containers-core` | `eclab.containers` | Core host-connector and WAN-access collection. |
| `engulf-clab-containers-pki` | `eclab.containers.pki` | PKI-enabled Debian and Fedora base-container collection. |
| `engulf-clab-ensure-checkout` | Library only | Shared safe Git checkout provisioning and update logic. |
| `engulf-clab-ensure-containerlab` | `engulf_clab.ensure_containerlab` | Finds, builds, or provisions Containerlab. |
| `engulf-clab-image-build` | `engulf_clab.image_build` | Maps topology images and node-env parameters into the neutral graph and dispatches builds. |
| `engulf-clab-dockerfile-build` | `engulf_clab.dockerfile_build` | Contributes node-owned Dockerfile recipes and build-only image nodes. |
| `engulf-clab-image-archive` | `engulf_clab.image_archive` | Creates node images from saved Docker image archives selected per node. |
| `engulf-clab-ensure-vrnetlab` | `engulf_clab.ensure_vrnetlab` | Finds or provisions a vrnetlab checkout. |
| `engulf-clab-vrnetlab-build` | `engulf_clab.vrnetlab_build` | Builds vrnetlab node images. |
| `engulf-clab-license-pool` | `engulf_clab.license_pool` | Shares license files safely across labs. |
| `engulf-clab-freeze` | `engulf_clab.freeze` | Produces sanitized, portable frozen lab archives. |
| `engulf-clab-lab-registry-api` | Contract only | Typed access to the shared persistent lab inventory. |
| `engulf-clab-lab-registry` | `engulf_clab.lab_registry` | Tracks deployed and explicitly discovered labs for inventory consumers. |
| `engulf-clab-reclaim` | `engulf_clab.reclaim` | Reclaims Docker storage for selected, destroyed, or stopped labs, including `destroy --reclaim`, and reports resources and storage reclaimed. |
| `engulf-clab-consumption` | `engulf_clab.consumption` | Reports deployed, stopped, and reclaimed state with CPU, RAM, lab-directory, and image storage. |
| `engulf-clab-freeze-api` | Contract only | Typed extension hooks for optional freeze and defrost contributors. |
| `engulf-clab-pki-api` | Contract only | Immutable authorized node-PKI projections for independent consumers. |
| `engulf-clab-pki` | `engulf_clab.pki` | Generates PKI catalogs, identities, and least-privilege node views. |
| `engulf-clab-pki-linux-core` | `engulf_clab.pki_linux_core` | Provides the portable Linux PKI runtime asset image. |
| `engulf-clab-pki-linux-debian` | `engulf_clab.pki_linux_debian` | Provides the Debian 13 family installer asset image. |
| `engulf-clab-pki-linux-fedora` | `engulf_clab.pki_linux_fedora` | Provides the Fedora 44 family installer asset image. |
| `engulf-clab-vrnetlab-fortigate-pki-injector` | `engulf_clab.vrnetlab_fortigate_pki_injector` | Injects authorized PKI paths into FortiGate vrnetlab nodes. |
| `engulf-clab-wan` | `engulf_clab.wan` | Creates DHCP/NAT WAN bridges for marked nodes. |
| `engulf-clab-lab-parser` | `engulf_clab.lab_parser` | Shared original-topology and deferred-mutation API. |
| `engulf-clab-lab-writer` | `engulf_clab.lab_writer` | Renders deferred mutations into a temporary topology. |
| `engulf-clab-sticky-ip` | `engulf_clab.sticky_ip` | Assigns stable private management subnets and fixed node IPs after topology parsing. |

## Packaged containers

Active collection plugins provide reusable node images without copying their
Dockerfiles into each lab. List them with `eclab --eclab-containers-help`. A
collection owns the image namespace derived from its plugin ID. The core
`eclab.containers` collection provides network helpers, while the PKI-scoped
`eclab.containers.pki` collection provides `debian` and `fedora` bases that
application images can inherit:

```dockerfile
FROM eclab.containers.pki/debian:latest
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
```

The inherited PKI entrypoint applies the node's projected trust before running
the final command. The core collection can map an external host with
`host-connector`:

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

## Freezing and defrosting a lab for sharing

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

`eclab defrost ARCHIVE` reverses that on the receiving side. It expands the
archive into `<archive-name>` or `--into DIRECTORY`, removes the
`x-engulf-clab-freeze` metadata, restores launcher and bundled tool
permissions, prepares the runtime, points nodes at bundled Docker image
archives that carry their exact image, and resolves every redacted license from
`--license NODE=VALUE`, `ECLAB_LICENSE_<NODE>`, `ECLAB_LICENSE`, or an
interactive prompt. It stages beside the destination and publishes atomically,
so a failed expansion leaves no partial lab, and it replaces an existing
directory only with `--force` and only when an earlier defrost recorded it. The
result is an ordinary lab directory holding real local license selections: do
not commit or re-share it; freeze redacts them again for the next archive.

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

Use Python 3.12 or newer and the repository `.venv` when present. Keep changes
focused and run the narrowest relevant checks, such as unit tests, bytecode
compilation, plugin discovery, and `ruff check`.

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

For a side-by-side baseline, install
`engulf-clab-develop-eclab-lab-static` and explicitly invoke
`$develop-eclab-lab-static`. Its target is distinct from the generated
`$develop-eclab-lab` skill.
Commits that change wrapper, plugin, or MCP behavior or documentation must
include exactly one review trailer:

```text
Skill-Impact: updated
```

or `Skill-Impact: none`.

## License

This monorepo and every plugin package are MIT licensed. Individual plugin
licenses carry `Copyright (c) 2026 Karel Chanivecky`.
