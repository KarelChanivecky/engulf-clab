# Plugin Instructions

This directory contains the `engulf-clab-ensure-containerlab` plugin
distribution.

## Purpose

The plugin makes a `containerlab` executable available to normal wrapper calls.
It uses an executable `CONTAINERLAB_BIN`, a valid `CONTAINERLAB_DIR` checkout,
or an existing `containerlab` on `PATH`; otherwise it provisions a managed
checkout and builds `bin/containerlab` from it.

Managed checkout selection and safe staged clones belong in
`engulf-clab-ensure-checkout`. Keep Containerlab repository validation and Go
build details in this package. Plugin callbacks must use only `api.logger` for
diagnostics and must restore the process `PATH` after each call.

## Compatibility

- Goal catalog: `engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper`
- Application declaration: `engulf.plugins.v1.application.engulf_clab`
- Plugin ID: `engulf_clab.ensure_containerlab`

