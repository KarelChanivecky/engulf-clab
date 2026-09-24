# engulf-clab-vrnetlab-static-image-provider

Selects local qcow2 or archive inputs for vrnetlab nodes and publishes their
absolute paths to the shared `engulf-clab-vrnetlab-build` plugin. The package
owns source flags, environment variables, YAML controls, and completion; the
builder owns image construction. Its freeze hook describes VM inputs without
building, allowing selective image capture or lean recipient variables.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
