# Contributing

This package owns `engulf-clab.pki-linux-fedora/installer:latest`. Keep the external core
image dependency explicit and register the provider from the application entry point for
recursive eclab deploys; the Docker-image-goal entry point alone is insufficient. Keep Fedora
44 first-class and startup behavior delegated to the distribution-neutral runtime.
