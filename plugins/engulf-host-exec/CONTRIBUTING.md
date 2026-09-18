# Contributing

Keep privilege decisions at execution boundaries. `root_command` constructs
argv without running it; `require_root_access` authenticates before detached or
parallel work. Docker selection uses the user's Docker configuration and active
context metadata, never a speculative privileged retry of a failed mutation.
Detached launches must let sudo authenticate before it backgrounds the child;
do not create a new terminal session before sudo can use its cached ticket.

The library owns no state or leases. Callers retain their normal lifecycle,
logging, resource leases, error handling and return-code interpretation.
Do not import wrapper runtime packages or introduce process-wide PATH changes.

Validate with `.venv/bin/python -m pytest -q plugins/engulf-host-exec/tests` and
the wrapper, WAN, Docker-image and Docker-client consumer suites.
