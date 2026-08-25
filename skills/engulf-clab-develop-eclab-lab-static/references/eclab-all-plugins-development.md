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
- Keep the README's included-distribution table synchronized with dependencies.
- Do not depend on `engulf-clab` or `engulf-clab-mcp`; callers choose the wrapper
  and optional control plane independently.
- Preserve compatible upper bounds so publishing one plugin cannot silently
  install an unsupported major contract.
- Validate metadata with a package build, inspect the wheel for code-free
  contents, install it into a temporary environment with the wrapper, run
  `python -m pip check`, and inspect `eclab --engulf-plugin-list`.
- Regenerate the bundled skill README/AGENTS snapshots after changing this
  package's documentation or dependency catalog.
