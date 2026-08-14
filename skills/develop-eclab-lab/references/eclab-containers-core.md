# engulf-clab-containers-core

Core collection plugin `eclab.containers`. Its package-owned recipes are built
automatically before deploy when a topology references one of these images:

| Image | Purpose |
| --- | --- |
| `eclab.containers/host-connector` | Map lab-facing VIPs to hosts reachable through management `eth0`. |
| `eclab.containers/ldap-389ds` | 389 Directory Server with a Cockpit management UI. |
| `eclab.containers/proxy-node` | Squid HTTP/HTTPS and Dante SOCKS5 proxies with a control UI. |
| `eclab.containers/ubuntu-firefox-gui` | Ubuntu XFCE and Firefox served through noVNC. |

Run `eclab --eclab-containers-help` to inspect the active catalog. A topology
uses the image name directly; the container manager injects the package recipe,
Linux kind, and `image-pull-policy: Never` before the Dockerfile builder runs.

## Host connector

```yaml
topology:
  nodes:
    outside-vm:
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

## LDAP / 389 DS

Use `eclab.containers/ldap-389ds` for lab authentication. Keep ports 389/636 on
the data plane and normally publish only Cockpit 9090 to the host. Defaults are
`LDAP_INSTANCE=localhost`, `LDAP_BASE_DN=dc=lab,dc=local`, directory-manager
credentials `cn=Directory Manager` / `admin123`, and Cockpit credentials
`admin` / `admin`. Bind-mount a lab-specific LDIF over
`/etc/dirsrv/seed.ldif` when changing the suffix, users, or groups. See the
packaged `containers/ldap-389ds/README.md` for seeding and replication guidance.

## Proxy node

`eclab.containers/proxy-node` exposes Squid on 8888, Dante SOCKS5 on 1080, and
its control UI on 8890. Set `SOCKS_EXTERNAL_IP` to the node's data-plane address
and optionally `SOCKS_WAIT_DNS` to delay Dante until lab DNS is ready. A lab
using a different data-plane address must bind-mount a matching `sockd.conf`.
See the packaged proxy README for routes, state, and browser usage.

## Firefox GUI

`eclab.containers/ubuntu-firefox-gui` exposes noVNC on 6080. Set
`GUI_RESOLUTION` to override the display size. Optional `FIREFOX_CA_CERT`,
`FIREFOX_CLIENT_P12`, `FIREFOX_CLIENT_P12_PASSWORD`, and
`FIREFOX_CA_NICKNAME` values control startup certificate import. Keep proxy
policies, certificates, IP addresses, and routes in the consuming lab; see the
packaged GUI README for PAC and Containerlab examples.
