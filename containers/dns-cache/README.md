# DNS cache container

Standalone recursive DNS forwarder with a persistent SQLite answer cache for
selected domain suffixes. It tries configured upstream servers first and can
serve a previously successful answer when they fail. The cache does not expire
entries by DNS TTL; cached records are returned with TTL zero.

## Build

Build the image from the repository root:

```bash
docker build -t eclab-dns-cache:latest ./containers/dns-cache
```

Then use the locally built image as a normal Containerlab `linux` node image.
Containerlab remains the topology language and runtime; this container does not
require or register an eclab plugin.

## Topology example

```yaml
name: dns-cache-demo
topology:
  nodes:
    dns:
      kind: linux
      image: eclab-dns-cache:latest
      binds:
        - ./dns-cache-data:/var/lib/eclab-dns-cache
      env:
        ECLAB_DNS_CACHE_DOMAINS: "corp.example,svc.corp.example"
        ECLAB_DNS_CACHE_UPSTREAM: "udp://192.0.2.53:53,dot://dns.example.net:853"
        ECLAB_DNS_CACHE_UPSTREAM_TIMEOUT: "5"
      exec:
        - ip address replace 198.19.0.1/24 dev eth1
    client:
      kind: linux
      image: alpine:3.24
      exec:
        - ip address replace 198.19.0.2/24 dev eth1
        - printf 'nameserver 198.19.0.1\\n' > /etc/resolv.conf
  links:
    - endpoints: ["dns:eth1", "client:eth1"]
```

Configure clients to use the DNS node's lab-facing address. The resolver
listens on UDP and TCP port 53. It uses its management interface to contact
upstreams. Assign lab addressing and routes according to the lab design.

## Configuration

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ECLAB_DNS_CACHE_DOMAINS` | Required | Comma-separated suffixes eligible for caching; each suffix also matches its subdomains. |
| `ECLAB_DNS_CACHE_UPSTREAM` | `udp://1.1.1.1:53` | Ordered, comma-separated recursive DNS endpoints. |
| `ECLAB_DNS_CACHE_UPSTREAM_TIMEOUT` | `5` seconds | Total timeout budget across upstream endpoints; accepted range is 0.1–120 seconds. |
| `ECLAB_DNS_CACHE_DB` | `/var/lib/eclab-dns-cache/cache.sqlite3` | Internal SQLite database path. |
| `ECLAB_DNS_CACHE_LOG_LEVEL` | `INFO` | Resolver process log level. |

Upstream transport syntax:

- Cleartext DNS: bare `host:port`, `cleartext://host:port`, `udp://host:port`,
  or `tcp://host:port`. Bare endpoints and `cleartext://` use UDP.
- DNS over TLS: `dot://host[:853]` or `tls://host[:853]`.
- DNS over HTTPS: `doh://host[/path]` or `https://host[/path]`; the default
  path is `/dns-query` and the default port is 443.

Encrypted transports validate certificates using the container's system CA
store and check the endpoint hostname. DoH uses HTTPS POST with the DNS wire
message media type. Hostnames must resolve through the container's system
resolver. Separate endpoints with commas; commas are not supported inside DoH
URL query strings.

The DNS suffix list is required. Only successful upstream answers with answer
records for those suffixes enter the cache. Queries outside the configured
suffixes are forwarded but not stored. Cache keys include query name, type,
and class. Each query tries configured upstream endpoints in order; if they
fail or return DNS errors, a matching cached answer is returned. Without a
cache hit, the resolver returns the final DNS error or `SERVFAIL`.

## Cache persistence contract

The cache directory is **`/var/lib/eclab-dns-cache`**. The SQLite database is
stored there by default at `cache.sqlite3`. Bind a host directory to that exact
container path to retain answers after Containerlab removes and recreates the
node:

```yaml
binds:
  - ./dns-cache-data:/var/lib/eclab-dns-cache
```

The relative source path is resolved from the topology file directory. The
directory is writable by the container and must be backed up or cleared using
normal host file operations while the node is stopped. Without the bind, the
database is part of the container filesystem and will not survive container
removal. The container does not create or clean up host paths.

## Security and limitations

This is a forwarding resolver with cached fallback, not a primary authoritative
zone server and not a DNSSEC validator. It has no client authentication; keep
its lab-facing network trusted and do not expose port 53 to untrusted clients.
The default upstream is public DNS. Configure internal recursive resolvers when
names must remain private or use split-horizon data. Because entries do not
expire, a record can remain stale throughout an upstream outage; a successful
later upstream response replaces its cached entry.

Inspect startup failures with `docker logs clab-<lab>-dns`. Check the configured
domain list, endpoint URL syntax, certificate trust, upstream reachability, and
the writable bind mount. A cache answer is only available if the node resolved
that exact name and record type successfully at least once.
