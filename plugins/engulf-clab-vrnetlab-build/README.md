# engulf-clab-vrnetlab-build

Reproducible vrnetlab image builds and source selection.

The package supplies separate executable-wrapper and Docker-image goal adapters
while sharing one invocation-scoped vrnetlab recipe provider between them.
Its freeze hook describes VM inputs without building, allowing selective image
capture or lean recipient variables.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
