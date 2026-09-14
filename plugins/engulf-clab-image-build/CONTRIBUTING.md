# Contributing

This package owns only the executable-wrapper/Containerlab adapter. Keep graph,
provider, Dockerfile, recursion, and scheduling policy in the neutral API/core
packages. The adapter may inspect the parser's materialized topology but must
not parse provider-specific controls or import provider implementations.

Run after topology mutators and graph contributors and before the lab writer.
Analysis remains side-effect free; Docker runs only during preparation. Keep
the old job option and environment spelling compatible. Node image parameters
apply only to that exact image and must never be copied into requirements found
through recursion. Validate this package with parser, Dockerfile, container
manager, core resolver, discovery, and skill tests.

Keep recursive roots, literal `FROM` dependencies, dependency-first execution,
cache behavior, ranked fallback, and derived pull-policy behavior directly
visible in the compact `PluginSchema` capability surface.
Declare the parser, writer, and schema ordering edges only in
`engulf.plugins.v1.dependency.engulf_clab_image_build` package metadata;
Engulf rejects a class-level `plugin_dependencies` declaration.
The low-authority fallback must accept an exact local tag before attempting a
registry pull; higher-authority provider recipes retain their declared policy.
`USAGE.md` may elaborate on them but must not be their only discovery path.

Provisioning leases are scoped to the shared scheduler call. The resulting
images and Docker cache are retained outputs, not transient resources, and the
topology mutation exists only in invocation context. A later preparation
failure therefore requires no `prepare_failed()` cleanup in this adapter.
