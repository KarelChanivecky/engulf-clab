# PKI base containers

The `eclab.containers.pki` collection provides two reusable trust-aware bases:

| Image | Distribution | Purpose |
| --- | --- | --- |
| `eclab.containers.pki/debian` | Debian 13 | Install the Linux PKI runtime and Debian trust prerequisites. |
| `eclab.containers.pki/fedora` | Fedora 44 | Install the Linux PKI runtime and Fedora trust prerequisites. |

Install the collection with eclab and inspect the active catalog:

```bash
python -m pip install engulf-clab engulf-clab-containers-pki
eclab --eclab-containers-help
eclab --engulf-plugin-list
```

The dependency set installs the container manager, PKI projection plugin, and
the portable, Debian, and Fedora PKI image providers. Another edition must allow
the same plugin IDs; use that edition's launcher for help and catalog commands.

## Inherit a base

Applications belong in descendants, not these bases:

```dockerfile
FROM eclab.containers.pki/debian:latest

RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium curl firefox-esr && \
    rm -rf /var/lib/apt/lists/*

CMD ["sleep", "infinity"]
```

Use `dnf` after `FROM eclab.containers.pki/fedora:latest` for a Fedora
descendant. Recursive image provisioning recognizes the literal `FROM`, builds
the selected PKI base, its distro installer, and the portable runtime in
dependency order, then builds the descendant.

Both bases declare:

```dockerfile
ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--"]
CMD ["sleep", "infinity"]
```

A descendant may replace `CMD`. If it declares an application entrypoint, it
must retain the wrapper explicitly:

```dockerfile
ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--", "/usr/local/bin/start"]
CMD ["--foreground"]
```

Replacing `ENTRYPOINT` without the wrapper bypasses PKI initialization. The
runtime detects applications at every startup, so applications installed in a
descendant are supported even though the base recorded an earlier build-time
capability snapshot.

## Use in a topology

Containerlab YAML remains the topology language. A base can also run directly:

```yaml
topology:
  defaults:
    env:
      ECLAB_PKI_MANIFEST: ./pki.yaml
  nodes:
    client:
      kind: linux
      image: eclab.containers.pki/debian
      env:
        ECLAB_PKI_CERTIFICATES: workstation-user
        ECLAB_PKI_REQUIRED: "true"
```

The PKI manifest must use version 2. The PKI plugin resolves the node request,
mounts only its authorized view read-only, injects `ECLAB_PKI_ROOT`, and removes
request variables from the derived runtime environment. Do not author
`ECLAB_PKI_ROOT` or its mount yourself. The source topology remains unchanged.

`ECLAB_PKI_SYSTEM_TRUST=augment|isolated` defaults to `augment`.
`ECLAB_PKI_IDENTITY_DEFAULT` selects the non-browser fallback, while
program-specific selectors such as `ECLAB_PKI_IDENTITY_CURL` override it. The
Linux runtime also supports the browser, Playwright, curl, and nginx controls
documented by `engulf-clab-pki-linux-core`. The bases provide CA certificates,
OpenSSL, Python, and NSS tools; they deliberately omit target applications.

## Lifecycle, security, and troubleshooting

At startup the wrapper reads inventory version 2, applies selected trust and
identity integration, exports generated adapter paths, and executes the final
command. A missing projection is a no-op unless `ECLAB_PKI_REQUIRED=true`.
Runtime state stays inside the container and the projected inventory is
read-only. Successful destroy removes node views and containers; persistent PKI
authorities and cached Docker images follow their owning plugins' lifecycle.

Projected private keys are secrets. Do not copy them into descendant layers,
logs, source trees, or shared volumes. `isolated` changes supported system-client
configuration but does not disable browser built-in roots; follow the Linux PKI
runtime guide for that boundary.

If a base is missing, confirm `eclab.containers.pki`,
`engulf_clab.containers`, the image dispatcher, and the three Linux PKI image
providers are active. For build failures, inspect dispatcher diagnostics and
Docker access. For startup failures, inspect `docker logs clab-<lab>-<node>`,
run `eclab pki effective -t TOPOLOGY`, verify the requested identity names, and
confirm the descendant retained the PKI entrypoint.
