# eclab.containers/proxy-node

Browser-access proxy node for eclab-managed labs. Use this node when the user
wants host browser access into lab traffic: one container runs a Squid
HTTP/HTTPS forward proxy, a Dante SOCKS5 proxy, and a small control UI for
changing Squid behavior at runtime. Prefer this tested recipe over ad hoc
port-forwarded applications or custom proxy implementations.

## Guide

- Image contents and generic/lab-owned configuration
- Containerlab topology and published ports
- Squid control UI and generated configuration
- Dante data-plane and DNS readiness
- Browser usage, validation, security, and troubleshooting

## Contents

- `Dockerfile`: image derived from `ubuntu/squid` with Python, `squidclient`,
  `dante-server`, and standard network tools (`ip`, `ping`, `curl`, `dig`,
  `tcpdump`, etc.).
- `squid.conf`: default Squid config for port `8888`, local cache-manager
  access, header suppression, and no cache. Baked into the image.
- `sockd.conf`: Dante SOCKS5 config, defaulting to port `1080`. Baked into
  the image with a placeholder `external` address; labs must override it.
- `proxy_control.py`: minimal browser UI on port `8890` for changing Squid
  behavior (header suppression, caching, parent proxy). Rewrites
  `/etc/squid/squid.conf`, which the entrypoint watches and reloads.
- `proxy_start.sh`: container entrypoint. Starts the UI, Squid, and Dante;
  fixes Squid log ownership; tails all daemon logs to the container log; and
  reloads Squid when the config changes.
- `proxy-control.json`: default control-UI state, baked to
  `/etc/squid/proxy-control.json`.

The image is generic: it has no lab IP addresses, routes, or credentials
(other than documented placeholder defaults). Lab specifics arrive through
bind mounts and the topology's `exec` steps.

Runtime environment is intentionally small:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SOCKS_EXTERNAL_IP` | Unset | Expected data-plane IP and readiness gate for Dante; must match `external` in `sockd.conf`. |
| `SOCKS_WAIT_DNS` | Unset | Expected nameserver; Dante waits for the exact resolver entry and a successful test lookup. |

The address wait is bounded at 120 seconds and DNS wait at 300 seconds. A timeout
is logged and Dante starts anyway; neither wait blocks the already running
Squid service or control UI.

## Topology

Use one node for both client and proxy. The node should connect to the
traffic-path appliance's client-side interface. Expose:

- `8888:8888` for the default Squid HTTP/HTTPS proxy
- `1080:1080` for the default Dante SOCKS5 proxy
- `8890:8890` for the proxy configuration UI

Example:

```yaml
proxy:
  kind: linux
  image: eclab.containers/proxy-node
  ports:
    - 127.0.0.1:8888:8888
    - 127.0.0.1:1080:1080
    - 127.0.0.1:8890:8890
  env:
    SOCKS_EXTERNAL_IP: "10.1.100.11"
  binds:
    - configs/sockd.conf:/etc/sockd.conf:ro
    - configs/proxy-control.json:/etc/squid/proxy-control.json
  exec:
    - ip addr add <client-ip>/<prefix> dev eth1
    - ip link set eth1 up
    - ip route replace default via <fgt-client-ip> dev eth1
```

Link it to the traffic-path appliance:

```yaml
- endpoints: ["proxy:eth1", "router:<client-port>"]
```

The `squid.conf`, `proxy_control.py`, and `entrypoint.sh` defaults are baked
in; mount lab overrides only where needed (typically `sockd.conf`, and
`proxy-control.json` when the lab uses a parent proxy). When your lab does
bind-mount its own `squid.conf`, keep it writable — the control UI on port
`8890` rewrites that file to apply settings and the entrypoint reloads Squid
on change, so a read-only mount silently reverts on the next Apply.

The image builds as `eclab.containers/proxy-node:latest` during `eclab deploy` via the
`eclab.containers` collection and engulf-clab's Dockerfile builder; no manual step is needed.
To build directly, use the package as the build context:

```bash
docker build --tag eclab.containers/proxy-node:latest \
  -f src/engulf_clab_containers_core/containers/proxy-node/Dockerfile src/engulf_clab_containers_core
```

## Dante/SOCKS Rules

If the lab needs a different Dante/SOCKS5 port, update both `sockd.conf` and
the `ports` mapping in the lab's topology. Do not expose a configurable SOCKS
port only in the UI; host access requires a matching Containerlab port
mapping.

Set Dante's `external` address to the proxy node's data-plane IP, not an
interface name, and pass the same address as `SOCKS_EXTERNAL_IP` so the
entrypoint waits until Containerlab's `exec` steps have assigned it before
starting `danted`. The baked-in `sockd.conf` uses the documentation-only
`192.0.2.10` placeholder; always replace it with a bind-mounted lab file.

If the proxy node uses lab DNS, also set `SOCKS_WAIT_DNS` to the lab
nameserver so the entrypoint waits until `/etc/resolv.conf` contains the
intended nameserver and a test lookup succeeds before starting `danted`;
otherwise early browser traffic can fail with temporary hostname resolution
errors. Both readiness waits run in a Dante-only background startup path after
Squid and the proxy UI have already started, and both time out instead of
wedging the container — never block or fail the working Squid HTTP proxy
because Dante is waiting on a data-plane IP or DNS readiness. On Ubuntu the
Dante daemon binary is `/usr/sbin/danted`.

Dante logs go to `/var/log/sockd.log` (see `logoutput` in `sockd.conf`); the
entrypoint `tail -F`s it alongside the Squid logs so
`docker logs clab-<lab-name>-proxy` shows SOCKS connection activity.

Do not recover a Containerlab-connected proxy node with plain
`docker restart`. Docker restart can recreate the container network namespace
without Containerlab's data-plane veth links, leaving only the management
interface and causing the `SOCKS_EXTERNAL_IP` wait to time out. Use
eclab/containerlab redeploy or recreate the lab node so links and `exec`
commands are applied again.

## User Instructions

Tell the user:

- Use Squid at `127.0.0.1:8888` for ordinary HTTP/HTTPS proxy testing.
- Use SOCKS5 at `127.0.0.1:1080` when browser DNS must happen inside the lab;
  in Firefox enable `Proxy DNS when using SOCKS v5`.
- Open `http://127.0.0.1:8890/` to change Squid behavior such as header
  suppression, caching, or parent-proxy settings.

## Validation

For runtime confirmation, use:

```bash
docker exec -it clab-<lab-name>-proxy squidclient -h 127.0.0.1 -p 8888 mgr:config
```

That checks the Squid daemon's loaded configuration, not merely the mounted
file.

## Control state

The UI reads and writes `/etc/squid/proxy-control.json` and regenerates
`/etc/squid/squid.conf`. Its supported fields are:

| Field | Default | Meaning |
| --- | --- | --- |
| `suppress_proxy_headers` | `true` | Remove common forwarding/cache identity headers. |
| `disable_cache` | `true` | Add `cache deny all`. |
| `parent_enabled` | `false` | Send ordinary requests through one parent proxy. |
| `parent_host` | Documentation placeholder | Parent hostname/address when enabled. |
| `parent_port` | `8080` | Parent port, clamped to 1–65535 by the UI. |
| `forward_proxy_auth` | `true` | Add Squid `login=PASS` for browser-supplied proxy authorization. |

The entrypoint watches the generated Squid configuration modification time and
requests a live reconfigure. The state mount and Squid configuration must be
writable by the container when persistence/customization is needed.

## Security and troubleshooting

Squid's lab default permits all clients, Dante's example permits broad access,
and the control UI has no authentication. Bind all host-published ports to
`127.0.0.1` unless the user explicitly accepts wider exposure and supplies host
firewall/authentication controls. Do not place real parent credentials in the
committed JSON state.

For diagnosis:

- inspect `docker logs clab-<lab>-proxy` for Squid, Dante, UI, readiness timeout,
  and reconfiguration output;
- query Squid's loaded config with the documented `squidclient` command;
- compare `SOCKS_EXTERNAL_IP` with the actual data-plane address and the
  `external` value in the mounted `sockd.conf`;
- verify `SOCKS_WAIT_DNS` appears exactly in `/etc/resolv.conf` and answers the
  entrypoint's lookup;
- verify host port mappings separately from the node's lab-side route; and
- redeploy rather than using plain `docker restart` when Containerlab veth links
  are missing.
