# Contributing

Keep the resolver deterministic, application-neutral, and free of file-format
assumptions beyond Dockerfile syntax. Provider callbacks are discovery only;
all host work happens during build execution. Never use a shell for Docker
commands or invoke callback-bound API objects from worker threads.

Preserve dependency-first ordering, authority-first provider selection,
terminal rejection, execution-time offer fallback, the default pull offer,
requirement-local parameters, cycle detection, conflict detection, complete lease
acquisition, and aggregate failure behavior.
The built-in unclaimed-image fallback uses a missing-only pull recipe: inspect
the exact canonical target under its image lease, reuse it when present, and
pull only when absent. Provider-authored pull recipes remain always-pull unless
they explicitly request missing-only behavior.
Archive recipes load with `docker load`, parse the reported `Loaded image:` and
`Loaded image ID:` lines as the only retag sources, and fail a source that the
load did not report and Docker does not already hold. Their outcomes are
classified as `loaded`, not `built`.
Test direct library use and the Engulf goal adapter. Run eclab adapter and
container-provider tests after changing shared behavior.
