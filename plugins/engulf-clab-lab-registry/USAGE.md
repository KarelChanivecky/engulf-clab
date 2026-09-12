# Lab registry

Install `engulf-clab-lab-registry` beside `engulf-clab`. The plugin publishes a
shared inventory snapshot through `engulf-clab-lab-registry-api`; it has no
operator command or topology extension.

The registry automatically records the canonical lab name, topology directory,
topology path, and exact deployed Docker image IDs after successful `deploy` and
`redeploy` commands. Registry consumers may contribute complete observations,
which lets commands such as `eclab consumption -t ...` and
`eclab consumption --all` seed labs installed before registry activation.

Records are keyed by lab name plus canonical topology directory. Upserts replace
image IDs with the newest complete observation while preserving a known topology
path and deployment history. Destroy does not remove a record because lab files
and images can remain on disk. Consumers decide whether a retained record still
owns resources; the registry does not recursively scan or delete lab files.

The versioned registry is stored in Engulf-managed user state. This plugin owns
every read and write: it loads the snapshot before consumers run and applies
their observations in one short transaction after the goal completes, so an
interrupted command discards that run's consumer observations rather than
recording them. An unreadable registry is reported as a warning, serves an empty
inventory for that invocation, and is left on disk unmodified instead of being
overwritten. It contains paths and Docker image IDs but no credentials,
topology contents, resource measurements, or container output. A tracking error
is logged and never changes the result of a successful deployment. Docker access
is used only to observe completed deployments; no container or image is changed.

There are no leases or explicit cleanup steps. Removing the plugin stops future
tracking but does not alter labs. Removing its Engulf-managed user state forgets
inventory history and should be done only when no installed consumer needs it.
