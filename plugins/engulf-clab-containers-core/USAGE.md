# engulf-clab-containers-core

Core collection plugin `eclab.containers` supplies package-owned helper images.
Install it with the container manager, then inspect the active catalog:

```bash
python -m pip install engulf-clab-containers engulf-clab-containers-core
eclab --eclab-containers-help
```

Version 0.3.0 and later requires the Engulf 1.2 plugin APIs used for
package-declared dependency ordering and separate goal-adapter identities.

The distribution publishes two thin adapters over the same immutable recipes:
the `eclab.containers` executable-wrapper collection adapter and the
`eclab.containers.images` application-neutral `org.engulf.docker-image`
provider adapter. The distinct plugin IDs keep each adapter scoped to its exact
goal; both still serve the `eclab.containers/*` image namespace. A non-eclab
Engulf application can therefore request these images through the generic
Docker image goal without parsing Containerlab YAML.

| Image | Purpose | Detailed guide (packaged) |
| --- | --- | --- |
| `eclab.containers/host-connector` | Map lab-facing VIPs to hosts reachable through management `eth0`. | `containers/host-connector/USAGE.md` |
| `eclab.containers/wan-access` | NAT one lab interface through management `eth0`, with optional DHCP. | `containers/wan-access/USAGE.md` |

A topology selects a recipe by its exact image name. The container manager
registers its package recipe as an image provision and injects only required
Containerlab runtime fields plus `image-pull-policy: Never` into a temporary
deploy topology. The source lab is unchanged.

## Common contract

Every maintained recipe uses normal Containerlab management networking: `eth0`
is management-facing and later interfaces are lab-facing. Do not select an
incompatible `network-mode`. Required Linux capabilities and sysctls are
injected; conflicting node values fail instead of weakening the recipe.

The images deliberately omit lab-specific addresses, credentials, routes,
certificates, directory contents, and proxy policy. Supply these through normal
Containerlab fields such as `env`, `binds`, `ports`, `exec`, or startup files.
Do not expose management services beyond loopback unless the lab threat model
permits it.

### Host connector

`host-connector` translates each configured lab-side VIP to an external IPv4 or
IPv6 target reachable through `eth0`, then returns replies through the original
lab interface. It is protocol-independent but has no port mapping, DHCP, VPN,
or application proxy. Read its guide for mapping syntax, mixed-family rules,
packet flow, and target-access security.

### WAN access

`wan-access` forwards and masquerades IPv4 traffic from exactly one lab
interface through `eth0`. With no `ECLAB_DHCP_*` value it provides static NAT
only; setting any supported DHCP value also assigns the gateway and starts
DHCP. Read its guide for defaults, validation, client configuration, and
diagnostics.

## Build and troubleshooting

The Docker daemon must be reachable by the selected launcher environment. The
first deploy builds the canonical `:latest` image from assets in the installed
wheel. Later deploys invoke `docker build` again and use Docker's normal layer
cache. Images remain cached after destroy; deploy again after upgrading the
collection.

If a recipe is missing, run `eclab --engulf-plugin-list` and confirm the core
collection, manager, image dispatcher, parser, and writer are active in the
same launcher. For a build failure, verify Docker access and inspect dispatcher
diagnostics. For startup or packet-flow failures, inspect `docker logs
clab-<lab>-<node>` and follow the selected image's guide.

A collection being visible in catalog help proves plugin discovery and packaged
metadata, not that Docker can build the image or that host ports are free.
Container health and application readiness remain the responsibility of the
image entrypoint and the consuming lab.

## Runtime schema discovery

The collection records every helper-container node variable and snapshots this
packaged `USAGE.md` before the runtime schema generator runs last. Generated
skills therefore reflect only an installed, active core collection.
