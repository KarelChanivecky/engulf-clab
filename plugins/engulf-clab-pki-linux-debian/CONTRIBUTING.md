# Contributing

This package owns `engulf-clab.pki-linux-debian/installer:latest`. Its Dockerfile must copy
the core runtime by external image reference so recursive image resolution provisions both
assets. Its application entry point must register the provider used by recursive eclab deploys;
the Docker-image-goal entry point alone is insufficient. Keep the installer safe for
Debian-family images and runtime detection authoritative.

The schema declaration uses `audience=SchemaAudience.SUPPORT` because this
package serves other plugins, not lab authors; the generated lab skill omits it.
Do not add topology controls, task routes, or node kinds to that declaration.
