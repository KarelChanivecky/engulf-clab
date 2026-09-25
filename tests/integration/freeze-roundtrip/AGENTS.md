# Freeze round-trip integration suite

These entrypoints intentionally build images and sequentially deploy/destroy
real FortiGate labs. Never add them to ordinary unit targets. Host-free runner
tests live in `test_runner.py` and must not require Docker or privileged access.

Do not read, assign, or modify license pools or registry state; licensing is
outside this suite's scope. Catalog edits must use `pki global edit`, compare
exact owned declarations on removal, and leave unrelated entries intact. Persist
ownership before deployment.

Keep runtime artifacts and logs owner-private. Treat FortiGate status, Docker
inspect, startup config, catalog contents and keys as private raw output; reports
contain only selected public observations or assertions. Never print credentials
or private key material. Keep eclab unprivileged in every mode.

An unmet prerequisite or unexecuted case is blocked, never a pass or silent skip.
Only cases that complete their assertions AND cleanup count toward passed pair
coverage. Do not weaken diagnostics or normalization to make a failing test pass.
