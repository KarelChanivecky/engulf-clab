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
| `engulf-clab-lab-parser` and `engulf-clab-lab-writer` | Immutable source-topology session and temporary derived-topology collector. |
| `engulf-clab-ensure-checkout` | Shared safe managed-Git-checkout support used by ensure plugins. |
| `engulf-clab-ensure-containerlab` | Containerlab executable discovery, managed checkout, update, and build. |
| `engulf-clab-ensure-vrnetlab` | Conditional vrnetlab checkout discovery and provisioning. |
| `engulf-clab-dockerfile-build` | Pre-deploy builds for node-declared Dockerfiles. |
| `engulf-clab-vrnetlab-build` | Pre-deploy vrnetlab image builds from qcow2/archive sources. |
| `engulf-clab-containers-api` | Typed contract for independently packaged container collections. |
| `engulf-clab-containers` | Active collection catalog and temporary topology injection. |
| `engulf-clab-containers-core` | Maintained host-connector recipe. |
| `engulf-clab-license-pool` | Leased shared license selection and lab-local copies. |
| `engulf-clab-wan` | Privileged edition-aware DHCP/NAT bridge management. |
| `engulf-clab-freeze` | Sanitized portable and strict offline lab archives. |

Included feature packages are Dockerfile builds, the packaged-container manager
and core collection, Containerlab and vrnetlab provisioning, vrnetlab image
builds, license pools, managed DHCP/NAT WAN bridges, frozen shareable archives,
and the topology mutation/collector infrastructure. Review the individual
package READMEs before enabling host-affecting features such as WAN bridges or
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

The meta-package pins every maintained feature to its compatible `0.1` release
line and the stable container API to its `1.x` line through transitive
dependencies. When a maintained plugin is added, removed, or moves to an
incompatible series, update this dependency set and this table in the same
release. The package contains no runtime configuration, source topology fields,
state, entry points, or cleanup behavior of its own.
