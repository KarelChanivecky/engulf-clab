# Contributing

Keep the resolver deterministic, application-neutral, and free of file-format
assumptions beyond Dockerfile syntax. Provider callbacks are discovery only;
all host work happens during build execution. Never use a shell for Docker
commands or invoke callback-bound API objects from worker threads.

Preserve dependency-first ordering, authority-first provider selection,
terminal rejection, execution-time offer fallback, the default pull offer,
requirement-local parameters, cycle detection, conflict detection, complete lease
acquisition, and aggregate failure behavior.
Test direct library use and the Engulf goal adapter. Run eclab adapter and
container-provider tests after changing shared behavior.
