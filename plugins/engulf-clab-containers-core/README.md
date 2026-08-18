# engulf-clab-containers-core

Core collection plugin `eclab.containers`. Its package-owned recipes are built
automatically before deploy when a topology references one of these images:

## Contents

- [Common container contract](#common-container-contract)
- [Host connector](#host-connector)
- [WAN access](#wan-access)
- [Build and runtime behavior](#build-and-runtime-behavior)
- [Troubleshooting](#troubleshooting)

```bash
python -m pip install \
  engulf-clab-containers \
  engulf-clab-containers-core
eclab --eclab-containers-help
```

| Image | Purpose |
| --- | --- |
| `eclab.containers/host-connector` | Map lab-facing VIPs to hosts reachable through management `eth0`. |
| `eclab.containers/wan-access` | NAT one lab interface through management `eth0`, with optional DHCP. |

Run `eclab --eclab-containers-help` to inspect the active catalog. A topology
uses the image name directly; the container manager injects the package recipe,
Linux kind, and `image-pull-policy: Never` before the Dockerfile builder runs.

## Common container contract

The collection plugin is declarative. It publishes absolute package-resource
paths and required Containerlab fields; the manager records temporary topology
mutations and the Dockerfile plugin performs builds. The source lab is not
modified, and images remain cached in Docker after destroy.

All maintained recipes require the normal Containerlab management network.
`eth0` is therefore management-facing and must not be replaced with an
incompatible `network-mode`. Connect lab links beginning with the next interface
unless the image-specific guide says otherwise. Required Linux capabilities and
sysctls are injected; conflicting explicit node values fail rather than weaken
the recipe.

The images deliberately avoid lab-specific addresses, credentials, routes,
certificates, directory contents, and proxy policy. Set those in topology `env`,
`binds`, `ports`, `exec`, startup scripts, or other normal Containerlab fields.
Do not publish management services to non-loopback host addresses unless the lab
threat model permits it.

## Host connector

```yaml
topology:
  nodes:
    outside-vm:
      kind: linux
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
        ECLAB_CONNECT_HOST_2: "2001:db8:10::50;2001:db8:20::50"
  links:
    - endpoints: ["router:eth1", "outside-vm:eth1"]
```

`eth0` must route to the external targets. Every other interface is lab-facing,
and every mapping is exposed on each lab interface with per-interface reply
routing. `ECLAB_CONNECT_HOST` and `_0` are aliases and cannot both be present;
numbered mappings may be sparse. VIP and target address families must match.

The recipe adds `NET_ADMIN`, enables IPv4/IPv6 forwarding, and disables reverse
path filtering needed by policy routing. It is a deterministic connector, not a
DHCP server, general WAN, VPN, or SSH endpoint. Configure each attached
appliance/client with the intended VIP route and security policy.
See the packaged `containers/host-connector/README.md` for packet flow, mapping
validation, health, security, and troubleshooting.

## WAN access

```yaml
topology:
  nodes:
    wan:
      kind: linux
      image: eclab.containers/wan-access
      env:
        ECLAB_DHCP_SUBNET: "198.19.0.0/24"
        ECLAB_DHCP_GATEWAY: "198.19.0.1"
  links:
    - endpoints: ["wan:eth1", "client:eth1"]
```

`eth0` carries the node's own default route. Exactly one other interface is
lab-facing, and traffic arriving there is forwarded and masqueraded through
`eth0`. DHCP is disabled when no supported `ECLAB_DHCP_*` variable is present;
in that mode, configure static interface addresses and routes with normal
Containerlab fields such as `exec`. Setting any supported DHCP variable enables
the DHCP defaults, assigns the gateway address, and starts `dnsmasq`.

The recipe adds `NET_ADMIN` and enables IPv4 forwarding. `dnsmasq` runs with
DNS resolution disabled (`--port=0`) when DHCP is enabled. See the packaged
`containers/wan-access/README.md` for static and DHCP examples, the full
environment reference, packet flow, health, and troubleshooting.

## Build and runtime behavior

The first deployment of a recipe builds its canonical `:latest` tag from the
Dockerfile embedded in the installed wheel. Later deploys still invoke
`docker build`, which uses normal Docker layer caching. Reinstalling or upgrading
the collection changes package-resource paths and build inputs; deploy again to
refresh the local image.

The Docker daemon must be reachable by the selected launcher environment. A
collection being visible in catalog help proves plugin discovery and packaged
metadata, not that Docker can build the image or that host ports are free.
Container health and application readiness remain the responsibility of the
image entrypoint and consuming lab.

## Troubleshooting

1. Run `eclab --eclab-containers-help` in the same launcher or edition used for
   deploy and confirm the canonical image name.
2. Run `eclab --engulf-plugin-list` and verify the collection, manager,
   Dockerfile builder, parser, and writer are active.
3. Check Docker access and builder output with targeted plugin logging.
4. For startup failures, inspect `docker logs clab-<lab>-<node>` and the
   matching image guide under `containers/host-connector/README.md` or
   `containers/wan-access/README.md`.
5. For data-plane failures, confirm interface numbering, routes, address
   families, injected capabilities, and lab-specific configuration.
