# engulf-clab-ensure-checkout

This is a shared Python library for the ensure-containerlab and
ensure-vrnetlab plugins. It is not a discoverable Engulf plugin and has no YAML
or user-facing environment configuration of its own.

It provides safe configured-or-managed Git checkout provisioning, daily update
bookkeeping, revision clamps, and the error types used by the consuming plugins.
Install it only when developing a dependent package; normal users should install
`engulf-clab-ensure-containerlab`, `engulf-clab-ensure-vrnetlab`, or
`engulf-clab-all-plugins` instead.
