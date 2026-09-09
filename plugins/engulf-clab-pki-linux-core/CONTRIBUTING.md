# Contributing

The image provider owns only `engulf-clab.pki-linux-core/runtime:latest`. The runtime must
remain distribution-neutral, idempotent, fail closed on malformed inventory and selectors,
and perform no package installation. Validate with the package tests and the Dockerfile parser
direct-consumer tests.

The application entry point must register the same provider used by the Docker-image goal
entry point. Without wrapper-side registration, recursive deploys treat this local image as an
unclaimed registry reference and fail when the tag is not already cached.

Application adapters may write only below `/opt/eclab-pki/state` or to an explicitly documented
integration-owned system location. The curl adapter owns `state/curl/.curlrc`; the nginx adapter
owns `state/nginx/identity.conf`, which is a server-context fragment and must never rewrite a
consumer's nginx configuration.

NSS trust must follow the resolved `trust/ca-bundle.pem`, never the incidental CA certificates
imported by PKCS#12. Run `nss_trust()` after `nss_import()` for every managed database,
including per-identity Firefox profiles and nodes without client identities. Chromium builds
disagree about where the user database lives, so `nss_databases()` returns `~/.pki/nssdb` and
the XDG location and startup manages both. Collapse the two to one entry by device and inode
rather than by resolved path, so a link or a bind mount onto a shared database is imported and
journalled once; never require a mount, since consumers may run without `CAP_SYS_ADMIN`. Fingerprint nicknames avoid subject-name collisions; `certutil -A` updates trust
even when NSS already holds the same certificate under its PKCS#12 nickname. Preserve unrelated certificates and
private keys. The database-local `eclab-pki-ca-bundle.pem` records owned trust; journal the
union before mutation and reduce it only after success so the next startup can clear stale
trust after selection changes or partial failure.

Run `.venv/bin/python -m pytest -q plugins/engulf-clab-pki-linux-core/tests` from the repository
root, plus the Dockerfile parser direct-consumer tests and `make check-skill`. The runtime
tests generate temporary certificates and exercise real NSS chain validation when `openssl`,
`certutil`, and `pk12util` are available; install NSS tools in the test environment to avoid
skipping those checks. When Chrome, Chromium, or Firefox is installed, the tests additionally
drive the real browser headlessly against a loopback HTTPS origin, since NSS trust flags alone
do not prove a browser reads the database the runtime wrote. Those tests point `HOME` and the
Firefox profile at temporary directories; tests must not change the host OS trust store or
browser databases.
