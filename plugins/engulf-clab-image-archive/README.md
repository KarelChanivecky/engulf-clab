# engulf-clab-image-archive

Loads node and recursive dependency images from declared archives or a
checksummed freeze manifest. Supplies read-only archive facts to freeze.

Creates node images from saved Docker image archives (`docker save` tarballs,
including `.tar.gz`) selected by a node environment variable, offered to the
shared image dispatcher as a provider.

- [Usage](USAGE.md) documents installation, configuration, lifecycle, security, and troubleshooting.
- [Contributing](CONTRIBUTING.md) documents implementation invariants and focused validation.
