# Plugin Instructions

This directory contains the `engulf-clab-all-plugins` meta-package.

## Purpose

This package installs every Engulf plugin distribution maintained in this
monorepo. It intentionally does not publish an Engulf plugin entry point of its
own.

## Maintenance

- Keep `pyproject.toml` dependencies synchronized with plugin packages under
  `plugins/`.
- Do not add runtime behavior here. This package should remain a shallow
  dependency bundle.
- When adding a new plugin distribution, add a dependency on that distribution
  here in the same change.
