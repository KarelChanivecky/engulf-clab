# engulf-clab-ensure-checkout

This is a shared Python library for the ensure-containerlab and
ensure-vrnetlab plugins. It is not a discoverable Engulf plugin and has no YAML
or user-facing environment configuration of its own.

It provides safe configured-or-managed Git checkout provisioning, daily update
bookkeeping, revision clamps, and the error types used by the consuming plugins.
Install it only when developing a dependent package; normal users should install
`engulf-clab-ensure-containerlab`, `engulf-clab-ensure-vrnetlab`, or
`engulf-clab-all-plugins` instead.

## Public API

```python
from engulf_clab_ensure_checkout import (
    CheckoutConfig,
    CheckoutError,
    UpdateConfig,
    ensure_checkout,
    update_checkout,
    update_requested,
)
```

| API | Responsibility |
| --- | --- |
| `CheckoutConfig` | Tool label, managed-state basename, configured-directory variable, repository variable, and default clone URL. |
| `ensure_checkout()` | Prefer a valid configured directory, then a valid managed checkout, otherwise clone to a staged sibling, validate it, and publish it atomically. |
| `UpdateConfig` | Tool label plus update and version-clamp variable names. |
| `update_requested()` | Interpret a nonempty version or a truthy update value as opting into Git checks. Empty, `0`, `false`, `no`, and `off` disable ordinary checks. |
| `update_checkout()` | For an opted-in clean Git checkout, rate-limit checks, fetch, apply a revision clamp or select a release/branch update, and report whether HEAD changed. |
| `CheckoutError` | Stable failure type for invalid managed state, missing Git, clone/validation failures, dirty worktrees, or Git update errors. |

The caller supplies the Engulf `StateStore`, environment mapping, tool-specific
checkout validator, and callback-bound diagnostic functions. It also owns the
user-scoped repository lease and any build step required after a changed
checkout. This package does not know what makes Containerlab or vrnetlab valid.

## Checkout selection

`ensure_checkout()` follows this order:

1. Resolve and validate the directory named by the configured-directory
   variable. An invalid configured value produces a warning and falls through.
2. Return the valid checkout at `state.path(config.basename)`.
3. Refuse to overwrite any existing invalid path at that managed location.
4. Require `git`, clone the configured/default repository into a temporary
   directory under the state root, validate it, and rename it into place.

The clone argv uses `git clone -- <repository> <staged-path>` without a shell.
A failed or invalid staged clone is removed with its temporary directory and
never becomes the managed checkout. If another protected caller publishes a
valid target first, that checkout wins.

## Update and clamp behavior

Update checks apply only to Git worktrees and only when requested. A directory
without Git metadata is returned unchanged. Check records are keyed by the
resolved checkout path and retain the requested version and branch; an identical
request is checked at most once per 24 hours.

A dirty worktree is rejected and is never reset or cleaned. With a nonempty
version clamp, the revision must resolve to a commit and is checked out detached.
Without a clamp, the helper fetches origin tags/refs when available, then chooses
the highest reachable version-shaped tag (`v1.2.3` or `1.2.3` form). If no such
tag exists, it fast-forwards the remembered/current/default branch from origin.
A checkout without an origin is left at its current revision with an
informational diagnostic.

This is update orchestration, not a general Git client: it does not merge,
rebase, reset, clean, delete, or repair user changes. Remove an unwanted managed
checkout explicitly and let the consuming ensure plugin recreate it.

## Development and testing

Use a temporary `StateStore`, fake validators, and an injected clone runner for
unit tests. Construct local Git repositories for update tests; automated tests
must not clone public repositories. Changes to this API require the
ensure-containerlab and ensure-vrnetlab test suites because both consume its
state and update semantics.
