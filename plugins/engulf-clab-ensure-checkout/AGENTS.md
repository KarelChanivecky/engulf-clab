# Plugin Instructions

This directory contains the `engulf-clab-ensure-checkout` support package.

## Purpose

It owns the generic managed-checkout lifecycle shared by the Containerlab and
vrnetlab ensure plugins: configured checkout selection, validation, staged Git
clone, and publication to user-scoped Engulf state. It is not itself an Engulf
plugin and must not publish plugin entry points.

Keep tool-specific validation and post-checkout build work in the corresponding
extension package. This package imports only `engulf_api` for `StateStore`.

