# Contributing

This package owns the one vrnetlab build implementation and the Docker image
recipe provider. It does not own source flags, environment variables, topology
source fields, CLI completion, or user-facing source-selection help. Those
contracts belong to independently installable providers.

The builder reads parser `EffectiveNode` snapshots for standard image values
and `ECLAB_VRNETLAB_TYPE`, then reads source paths from
`engulf-clab-vrnetlab-build-api`. Keep provider selection out of this package.
The source context is invocation scoped; never retain it or an `InvocationAPI`
on the singleton plugin object. Only the Docker recipe request map is held on
the provider object during the call, and it must be cleared after the call and
on both preparation failure paths.

When a request falls back to the API's `default` source, all such nodes must
have the same `ECLAB_VRNETLAB_TYPE`. Enforce this after collecting the complete
topology request set and before preparing image builds. Exact per-node sources
may serve nodes with different builder types.

Provider plugins must run before `engulf_clab.vrnetlab_build`; the shared
builder must run after topology parsing and before image graph resolution and
topology serialization. Declare these edges in this distribution's dependency
entry-point group. Keep `provide()` a pure lookup because the image resolver may
call it from worker threads.

Build work may parallelize across builder directories, but work sharing a
directory remains serial. Acquire all image and builder leases in the callback
thread before starting workers. Keep managed state reads and writes serialized,
and restore temporary builder and Docker context artifacts on every exit path.
