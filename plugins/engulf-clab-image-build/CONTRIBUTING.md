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
`USAGE.md` may elaborate on them but must not be their only discovery path.
