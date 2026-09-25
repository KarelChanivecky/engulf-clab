# engulf-clab-all-plugins

Convenience meta-package that installs every maintained `engulf-clab` plugin:

```bash
python -m pip install engulf-clab engulf-clab-all-plugins
```

It does not publish an Engulf plugin itself. Its dependencies do, and Engulf
discovers those installed entry points when `engulf-clab` runs.

## Included distributions

| Distribution | Installed capability |
| --- | --- |
| `engulf-clab-schema-api` | Stable partitioned-pipeline declaration and invocation-state contract. |
| `engulf-clab-schema` | Last-running compiler for one executable-selected inherited pipeline and exact Containerlab source. |
| `engulf-clab-develop-eclab-lab` | Static eclab command that installs and refreshes only the `develop-eclab-lab` Codex skill. |
| `engulf-clab-lab-parser` and `engulf-clab-lab-writer` | Immutable source-topology session and temporary derived-topology collector. |
| `engulf-clab-sticky-ip` | Stable private IPv4 or IPv6 management subnets and fixed node addresses. |
| `engulf-clab-ensure-checkout` | Shared safe managed-Git-checkout support used by ensure plugins. |
| `engulf-clab-ensure-containerlab` | Containerlab executable discovery, managed checkout, update, and build. |
| `engulf-clab-ensure-vrnetlab` | Conditional vrnetlab checkout discovery and provisioning. |
| `engulf-clab-vrnetlab-build-api` | Shared per-node source-path context for vrnetlab providers and builder. |
| `engulf-clab-vrnetlab-build` | Single shared backend that stages inputs and constructs vrnetlab images. |
| `engulf-docker-image-api` and `engulf-docker-image-core` | Neutral provider graph, recursive resolver, and dependency-first Docker scheduler. |
| `engulf-clab-image-build` | Topology image roots, node-env parameters, provider dispatch, and build orchestration. |
| `engulf-clab-dockerfile-build` | Node-owned Dockerfile recipes and build-only image nodes. |
| `engulf-clab-vrnetlab-static-image-provider` | Local qcow2/archive source provider, CLI, and topology controls for vrnetlab builds. |
| `engulf-clab-containers-api` | Typed contract for independently packaged container collections. |
| `engulf-clab-containers` | Active collection catalog and temporary topology injection. |
| `engulf-clab-containers-core` | Maintained host-connector and WAN-access recipes. |
| `engulf-clab-containers-pki` | PKI-enabled Debian 13 and Fedora 44 bases for direct use or inheritance. |
| `engulf-clab-license-pool` | Product-aware pool registration, automatic leased selection, and lab-local copies. |
| `engulf-clab-wan` | Privileged DHCP/NAT bridge management. |
| `engulf-clab-freeze` | Lean compatibility archives, pinned runtime archives, and offline lab archives. |
| `engulf-clab-lab-registry-api` and `engulf-clab-lab-registry` | Typed shared inventory plus persistent deploy/redeploy tracking. |
| `engulf-clab-reclaim` | Guarded Docker reclamation with measured storage-saved reporting. |
| `engulf-clab-consumption` | Deployed, stopped, and reclaimed state with resource reports. |
| `engulf-clab-freeze-api`, `engulf-clab-pki-api`, and `engulf-clab-pki` | Format-3 runtime and contributor contracts plus typed opt-in PKI generation and private node views. |
| `engulf-clab-pki-linux-core`, `engulf-clab-pki-linux-debian`, and `engulf-clab-pki-linux-fedora` | Runtime plus Debian/Fedora installer asset images for automatic Linux trust and identity integration. |
| `engulf-clab-vrnetlab-fortigate-pki-injector` | Automatic path-only installation of authorized PKI identities into FortiGate vrnetlab nodes. |
| `engulf-clab-vrnetlab-fortigate-license-injector` | Mounts a registered FortiGate license read-only for vrnetlab startup. |
| `engulf-clab-fortinet-operation-guard` | Rejects unsupported reconfigure, restart, and already-running deploy operations for Fortinet nodes. |

Included feature packages are Dockerfile builds, the packaged-container manager,
core and PKI collections, Containerlab and vrnetlab provisioning, vrnetlab image
builds, license pools, managed DHCP/NAT WAN bridges, resource-consumption reports, frozen shareable archives,
PKI catalogs, certificate mounts, FortiGate PKI and registered-license injection,
sticky management addresses, and the topology mutation/collector infrastructure. Review the individual package READMEs before
enabling host-affecting features such as WAN bridges or
automatic source updates.

To keep an installation minimal, install `engulf-clab` and only the feature
packages a lab uses instead of this meta-package.

## Verify an installation

The meta-package guarantees compatible dependencies, not activation by every
edition. Inspect the selected launcher after installation:

```bash
eclab --help
eclab --engulf-plugin-list
eclab --eclab-containers-help
python -m pip check
```

The first command shows active plugin help, the second shows source packages and
ordering when the diagnostic extension is installed, and the third shows the
active container collection catalog. Run the corresponding edition launcher
instead of `eclab` for an edition.

This package deliberately excludes the `engulf-clab` wrapper itself and the
optional `engulf-clab-mcp` control service. Install them explicitly. Removing
the meta-package does not necessarily remove its dependency packages; use the
Python environment's package manager to remove individual features.

## Compatibility and releases

The meta-package pins every maintained feature and stable API to its declared
compatible release line. When a maintained plugin is added, removed, or moves
to an incompatible series, update this dependency set and this table in the
same release. Stable image, container, lab-registry, schema, freeze, and PKI
projection APIs remain on compatible major lines. The package contains no
runtime configuration, source topology fields, state, entry points, or cleanup
behavior of its own.
