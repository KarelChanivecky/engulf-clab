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

The table below inventories the maintained capabilities in this repository.
The installed launcher's help and plugin list remain authoritative for the
features active in a particular environment or edition.

| Feature | What it provides |
| --- | --- |
| Containerlab-compatible `eclab` wrapper | Preserves ordinary Containerlab commands, flags, topology YAML, exit behavior, and relative-path semantics while Engulf plugins contribute preparation, mutation, execution, and cleanup around the native call. The reusable application definition also supports separately branded editions with controlled plugin sets. |
| Safe privilege boundary | Refuses to launch the wrapper itself as root or Windows administrator, reports `GoalPrivilegeError` without a traceback, and returns framework exit code 70. Features that need privileged host changes use their own explicit boundary, such as the local MCP daemon. |
| Package-discovered plugin system | Discovers independently installed plugins through Python entry points, enforces declared application and goal compatibility, resolves package-declared ordering, and exposes activation order, distribution, and version through `--engulf-plugin-list`. The `engulf-clab-all-plugins` meta-package installs the complete maintained plugin set. |
| Runtime help, diagnostics, and logging | Combines native wrapper help with concise help from every active plugin, offers the packaged-container catalog through `--eclab-containers-help`, supports global and per-plugin log levels, and keeps operational output on callback-bound Engulf loggers. |
| Shell completion | Installs Bash, Zsh, or Fish completion for the selected launcher; merges wrapper/schema candidates with an explicitly trusted native Containerlab completer, and retains schema-backed candidates when native completion is unavailable. |
| Stable workspace identity and managed state | Uses the selected topology's directory as the canonical workspace, or the current directory when no filesystem topology is selected. Engulf user/workspace state, short transactions, resource leases, and invocation contexts give plugins durable identities without rewriting source labs. |
| Topology selection, parsing, and environment expansion | Selects `-t`, `--topo`, or `--topology` consistently, discovers an unambiguous local topology when allowed, parses ordinary Containerlab YAML once into an immutable shared model, loads the lab environment file, expands supported variables, and exposes deferred mutations without giving mutators ownership of the source document. |
| Temporary topology writer | Applies ordered deferred mutations only to a derived topology beside the source, preserves relative references, forwards the effective path to Containerlab, and removes the temporary file after the call. The maintained pipeline never rewrites the source topology. |
| Containerlab discovery and managed builds | Resolves an explicit binary or directory, `PATH`, a prepared checkout, or managed user-state checkout; can clone/update a selected repository and revision, build Containerlab, and validate Docker availability. Per-invocation schema and source controls override persistent environment defaults. |
| Sudo-less Containerlab setup | Supports the Containerlab sudo-less setup workflow as an explicit wrapper operation while keeping the `eclab` Python process unprivileged and reporting host prerequisite or permission failures cleanly. |
| Shared safe-checkout engine | Gives Containerlab and vrnetlab provisioning a common API for canonical repository identity, locked clone/update operations, moving or fixed revisions, clamp behavior, recovery, and protection against unsafe or unrelated checkout paths. |
| vrnetlab discovery and provisioning | Resolves an explicit vrnetlab directory, environment selection, prepared checkout, or managed checkout; can clone/update the configured repository/version and publishes the exact selected source for builders and runtime-schema generation. |
| Application-neutral Docker image API | Defines immutable image requirements, custom parameters, provisions, Dockerfile/pull/archive/vrnetlab recipes, provider responses, authority and fallback rules, graph contexts, and an independent `org.engulf.docker-image` goal contract usable without eclab or YAML. |
| Recursive image resolution and execution | Resolves roots and recursively discovered dependencies, ranks authoritative providers deterministically, honors terminal rejection and controlled fallback, detects cycles/conflicting recipes, and executes dependency-first. Independent branches may run concurrently while tag/source leases serialize conflicting Docker work. |
| Dockerfile dependency analysis | Discovers literal `FROM` and external `COPY --from` image dependencies, expands known global build arguments, rejects unresolved dynamic sources, excludes stage aliases and `scratch`, and combines discovered edges with explicit provider dependencies. |
| Topology image-build dispatcher | Converts final topology image references into graph roots, carries node-scoped image parameters, resolves every active provider, provisions images before Containerlab, and sets locally provisioned roots to `image-pull-policy: Never` in the derived topology. |
| Per-node Dockerfile builds | Declares Dockerfile, context, build arguments, Docker flags, and build-only base nodes through node environment controls. Build-only nodes contribute graph roots and dependencies but are removed from the deployable topology; Docker layer caching supplies rebuild freshness. |
| Docker image archives | Loads plain or compressed `docker save` archives, optionally selects and retags one source from a multi-image archive, supports missing-only reuse/reload policy, verifies ambiguity instead of guessing, and integrates archive images into the same dependency graph and leasing model. |
| vrnetlab appliance image builds | Selects node VM source artifacts and builder types, resolves source precedence, prepares the appropriate vrnetlab builder, fingerprints source/checkout/image identity, runs dependency-aware Make builds with configurable parallelism, safely restores pre-existing builder artifacts/tags after failures, and reuses matching successful outputs. |
| Extensible packaged-container manager | Lets independently published collections register immutable, package-owned Dockerfile recipes and required Containerlab runtime fields. It validates namespaces/assets/conflicts, canonicalizes managed `:latest` references, rejects unknown images in owned namespaces, preserves source YAML, and exposes the active collection catalog. |
| Core helper containers | Supplies `eclab.containers/host-connector` for protocol-independent IPv4/IPv6 VIP-to-external-host forwarding and source NAT, plus `eclab.containers/wan-access` for one-interface IPv4 masquerading with optional DHCP. Required capabilities, sysctls, and safe defaults are injected without embedding lab credentials or addressing. |
| PKI-aware Debian and Fedora base containers | Supplies `eclab.containers.pki/debian` and `/fedora` bases whose retained entrypoint installs a node's projected trust and identity configuration before the application starts. Descendants may add browsers, curl, nginx, Playwright, or other applications without baking private material into image layers. |
| License pools | Accepts a file, pool directory, variable reference, or frozen-license prompt; allocates safely across labs with sticky, least-recently-used, or round-robin behavior; supports exact per-node clamps; publishes a non-secret selection breadcrumb; and releases only the current lab's claims during lifecycle cleanup. |
| Managed DHCP/NAT WAN bridges | Recognizes explicitly marked Containerlab bridge nodes, validates subnet/gateway/pool/DNS/lease controls, selects an uplink, manages IPv4 forwarding, marked firewall/NAT rules, gateway addressing, and a packaged DHCP process, shares compatible bridges across workspaces, journals provisioning, and restores only resources it owns on last release. |
| Sticky management addressing | Assigns deterministic private management IPv4 or IPv6 subnets and stable per-node addresses after parsing; honors complete explicit addressing, configurable pools/exclusions/capacity, disable controls, and cross-lab allocation state while checking Engulf claims, Docker networks, host routes, and bounded traceroutes for conflicts. |
| PKI catalog and certificate generation | Uses manifest version 2 to merge local/global profiles, stores, authorities, and leaf declarations; resolves scoped references and node requests; generates persistent authorities and ephemeral identities under leases; backdates defaults for clock tolerance; creates least-privilege read-only node projections; and exposes the `pki global` path, init, edit, and validate operations plus a non-generating `pki effective` view. |
| PKI trust and identity policy | Supports natural-root trust, explicit include/exclude rules, requested private authorities, per-node certificate lists, configurable mount targets, inventory/fingerprint metadata, and `all`/`none` trust selection. Private keys appear only in authorized node views, while optional service declarations can inject supporting service nodes. |
| Portable Linux PKI runtime | Provides the common container entrypoint and adapters for system trust, isolated or augmented trust, default and application-specific identities, browsers/NSS, Playwright, curl, nginx, OpenSSL, and Python. Separate Debian 13 and Fedora 44 providers install distribution-specific trust prerequisites as recursively resolved image assets. |
| FortiGate PKI injection | For resolved `fortinet_fortigate` nodes, converts only the authorized typed PKI projection into validated `FOS_PKI_CA_CERTS` and `FOS_PKI_LOCAL_CERTS` path mappings, checks read-only mount/path containment and refname uniqueness, and leaves generation, secrets, rollback, and cleanup to the PKI owner. |
| Portable freeze archives | `eclab freeze` creates an atomic, sanitized lab archive containing a copied topology, exact Python package lock, best-effort wheelhouse, external VM inputs, and launcher. It records prior output archives to prevent recursive inclusion, applies built-in and lab-specific ignore rules, rejects unsafe external symlinks, redacts license selections, and never changes the source lab. |
| Offline freeze mode | Optionally bundles the active eclab environment, resolved Containerlab executable, exact vrnetlab checkout, and ordinary topology images for an offline, platform-compatible handoff; generated appliances, vendor VM inputs, and unavailable prerequisites fail explicitly instead of producing a falsely portable archive. |
| Atomic defrost and license restoration | Expands into a staged destination, validates archive safety, restores executable permissions and bundled tools/images, prepares a compatible runtime, resolves redacted licenses from CLI/environment/prompt sources, removes freeze metadata, and publishes atomically. `--force` replaces only a destination recorded by an earlier defrost. |
| Encrypted PKI secret export | Ordinary freezes contain no private material. An explicit passphrase-file flow exports only declarations marked `freeze.exportable`, encrypts them, and verifies fingerprints and canonical declaration identities during defrost. Typed freeze/defrost contributor APIs let optional packages extend archives without coupling to the core plugin. |
| Persistent lab registry | Records successful deploy/redeploy lab identity, canonical topology location, and exact Docker image IDs in versioned Engulf user state; retains destroyed labs for inventory, accepts complete observations from consumers, preserves corrupt state rather than overwriting it, and exposes a typed read/contribution API without scanning or mutating labs. |
| Resource consumption reporting | `eclab consumption` reports one lab or all known/deployed labs with `DEPLOYED`, `STOPPED`, or `RECLAIMED` state, instantaneous CPU, RAM, allocated lab-directory space, unique image storage, shared image storage, total storage, and a deduplicated total row. It handles moved tags, retained container root filesystems, unavailable measurements, registry seeding, and non-overlapping two-second polling. |
| Docker storage reclaim | `eclab reclaim` removes a selected lab's containers, writable layers, anonymous volumes, and exclusively owned images; guarded `--all` requires every known lab to be destroyed, while `--all --stopped` selects only non-running containerized labs. It preserves shared/unrelated images, lab files, networks, build cache, and non-Docker plugin resources, serializes deletion, attempts every selected object, and reports measured IEC storage saved. |
| Reclaimed lifecycle state | A non-running lab is `STOPPED` while unique image storage remains or Docker cannot prove it is zero, and becomes `RECLAIMED` once unique image storage is zero. Shared images do not prevent `RECLAIMED`, making the state describe per-lab reclaimable ownership rather than global Docker cache contents. |
| Runtime schema declaration API | Lets plugins declare concise task-routable controls, relationships, safety notes, wrapper flag/environment precedence, packaged documentation snapshots, and edition pipeline membership without embedding implementation-only contributor documentation. |
| Runtime schema compiler | Composes active plugin declarations with the exact selected Containerlab schema and matching Containerlab/vrnetlab node-kind documentation; records source revision, application metadata, provider ownership, pipeline lineage, and fingerprints; emits task catalogs, per-provider YAML, per-kind references, a manifest, and the final validation schema; and caches immutable artifacts per edition pipeline. |
| Runtime-generated Codex lab skill | Installs a concise static workflow plus the compiled catalog and task-relevant provider references for the exact active runtime. Installation refuses symlinked/unrelated targets, backs up recognized targets, publishes atomically, retains fingerprinted historical runtimes for existing conversations, repairs incomplete installs, and tracks roots for best-effort refresh after later eclab calls. |
| Static comparison skill | Keeps a separately packaged, separately named `develop-eclab-lab-static` baseline installable beside the generated skill for explicit comparative evaluation without taking over the generated target or refresh lifecycle. |
| Local privileged MCP control service | Provides an unprivileged stdio bridge to a root-owned, group-protected Unix-socket daemon with configured lab roots and service-owned profiles. Its typed tools list labs, validate bounded YAML/offline graphs, deploy, destroy one lab, inspect status, retrieve bounded node logs/diagnostics, and list/inspect/log/cancel retained asynchronous jobs—without arbitrary commands, flags, paths, environment secrets, node execution, or `destroy --all`. |
| MCP job safety and operations | Enforces stable lab IDs, caller override policy, one active lifecycle job per lab, bounded logs/results/retention, peer attribution, process-group cancellation with escalation, restart reconciliation, root-owned state, and structured safe errors. Different labs may run concurrently while duplicate work for one lab returns the existing job. |
| Comprehensive demonstration lab | Installs a non-plugin example lab combining a client, Fake WAN, FortiGate, DMZ, and work network so operators and contributors can exercise the integrated feature set from a self-contained starting point. |
| Independently publishable contracts and plugins | Keeps the wrapper, MCP service, demo installer, meta-package, shared checkout/image/container/freeze/PKI/registry/schema APIs, runtime implementations, providers, collections, and skills as separately versioned Python distributions, allowing applications and editions to install only the contracts and features they need. |

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

**Requires Python 3.14 or newer.** On an older interpreter `pip` reports
`No matching distribution found for engulf-clab`, which reads as though the
package does not exist; check `python3 --version` first, and install with an
explicit `python3.14 -m pip` when it is not your default.

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
python3.14 -m venv .venv
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
| `engulf-clab-reclaim` | `engulf_clab.reclaim` | Reclaims Docker storage for selected, destroyed, or stopped labs and reports the amount saved. |
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
