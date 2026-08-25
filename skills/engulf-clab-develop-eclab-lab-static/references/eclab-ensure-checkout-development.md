# Plugin Instructions

This directory contains the `engulf-clab-ensure-checkout` support package.

## Purpose

It owns the generic managed-checkout lifecycle shared by the Containerlab and
vrnetlab ensure plugins: configured checkout selection, validation, staged Git
clone, and publication to user-scoped Engulf state. It is not itself an Engulf
plugin and must not publish plugin entry points.

Keep tool-specific validation and post-checkout build work in the corresponding
extension package. This package imports only `engulf_api` for `StateStore`.

- Keep the library non-discoverable: no Engulf entry points, plugin object,
  topology fields, dynamic help, or application-specific prefix handling.
- Preserve configured-directory -> valid managed checkout -> staged clone
  selection. Never overwrite an existing invalid managed path.
- Clone with an argv and `--`, validate before publication, and publish by rename
  from a temporary directory under the same state root.
- Keep updates opt-in, Git-only, and rate-limited per resolved checkout plus
  requested clamp. Reject dirty worktrees; never reset, clean, rebase, or merge.
- Preserve release-tag selection and fast-forward-only branch behavior. Version
  clamps must resolve to commits and use detached checkout.
- Callers own tool-specific validation, user-scoped leases, callback logging,
  dependency checks, and rebuilds after a changed revision.
- Keep exported types/functions and README API tables synchronized. Treat a
  public signature or state-format change as compatibility-sensitive.
- Test with temporary local repositories and injected runners. Do not perform
  network clones. Run this package's suite plus both ensure-plugin suites.
- Regenerate the skill's checkout/development references after changes.
