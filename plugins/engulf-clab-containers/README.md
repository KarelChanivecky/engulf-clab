# engulf-clab-containers

The `engulf_clab.containers` manager consumes declarations from active Engulf
container-collection plugins. A lab selects a packaged recipe with an explicit
node image such as `eclab.containers/host-connector`. The manager injects the
recipe's valid Containerlab node fields and Docker build controls into the
temporary topology; the source topology is unchanged.

Run `eclab --eclab-containers-help` to list containers supplied by active
collections. The list is emitted through Engulf diagnostics.
