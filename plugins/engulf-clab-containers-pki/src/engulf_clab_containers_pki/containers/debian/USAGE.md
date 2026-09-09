# Debian PKI base

Inherit `eclab.containers.pki/debian:latest`, install the Debian applications
the lab needs, and replace `CMD` as required. The inherited
`/opt/eclab-pki/entrypoint --` must remain in the process path; a child that
replaces `ENTRYPOINT` must put that wrapper before its application entrypoint.

The base tracks Debian 13 and installs CA certificates, OpenSSL, Python, and NSS
tools. It contains no target application or PKI material. Runtime application
detection includes programs installed by descendants. See the package
`USAGE.md` for exact topology controls, lifecycle, security, and diagnostics.
