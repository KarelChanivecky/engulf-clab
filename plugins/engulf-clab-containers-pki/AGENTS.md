# PKI Container Collection Instructions

This package owns collection plugin `eclab.containers.pki` and the corresponding
`eclab.containers.pki/*` image namespace. Keep PKI-specific dependencies here;
the generic `engulf-clab-containers-core` collection must remain independent of
PKI packages.

- Keep the executable-wrapper collection adapter at `eclab.containers.pki` and
  the generic Docker-image adapter at `eclab.containers.pki.images`. Publish the
  same immutable recipes through both.
- Declare manager and schema ordering only in
  `engulf.plugins.v1.dependency.eclab_containers_pki`. Never set
  `plugin_dependencies` in code.
- Layer each base on its matching packaged installer provider, run
  `/opt/eclab-pki/install` during the build, and retain
  `/opt/eclab-pki/entrypoint` as the default entrypoint.
- Keep descendants viable: install only the trust runtime and prerequisites,
  detect applications at startup, and leave applications, certificates,
  manifests, credentials, and policy to consuming images and labs.
- Derive recipe paths from the installed package and keep every build input in
  the wheel. Do not invoke Docker or mutate topology or host state in this
  collection.
- Keep source, tests, schema, `USAGE.md`, and both image-specific guides aligned.
  Test provider/dependency declarations without a real Docker daemon.
