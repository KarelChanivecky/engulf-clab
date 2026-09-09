# Contributing

`engulf_clab_containers_pki.plugin` owns the two immutable
`ContainerDefinition` values, the executable-wrapper collection adapter, the
application-neutral image provider, and the runtime schema declaration. It may
import stable API packages but not the Engulf runtime.

The collection plugin ID is `eclab.containers.pki`; that identity produces the
Docker namespace `eclab.containers.pki/*`. The goal-specific image adapter uses
`eclab.containers.pki.images`. Manager and last-running schema ordering belong
only in the distribution dependency entry-point group. Keep the declaration and
its package test synchronized.

The Debian and Fedora Dockerfiles are intentionally thin. Each literal `FROM`
names the matching provider-owned installer image, allowing the shared resolver
to build the portable runtime and distro installer before the PKI base. Each
Dockerfile runs `/opt/eclab-pki/install`, retains the PKI wrapper as its
entrypoint, and supplies only an idle default command. Do not copy certificates,
manifests, applications, users, credentials, or policy into these images.

The inherited entrypoint is a compatibility boundary. Descendants may replace
`CMD`; a descendant with its own entrypoint must keep
`/opt/eclab-pki/entrypoint --` in front of the application entrypoint. Runtime
application detection must remain authoritative because applications are
normally installed after the base layer.

Validate without a Docker daemon:

```bash
PYTHONPATH=plugins/engulf-clab-containers-pki/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-containers-pki/tests
.venv/bin/python -m compileall -q plugins/engulf-clab-containers-pki/src
.venv/bin/python -m build --no-isolation plugins/engulf-clab-containers-pki
.venv/bin/python -m twine check plugins/engulf-clab-containers-pki/dist/*
make check-skill
```

Run the `engulf-clab-containers-api`, `engulf-clab-containers`, and
`engulf-docker-image-core` suites after changing the shared recipe boundary.
Inspect the wheel to confirm both Dockerfiles, both image guides, and top-level
documentation are packaged. A real Docker build is only appropriate when
explicitly authorized.
