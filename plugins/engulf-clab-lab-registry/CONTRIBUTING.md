# Contributing to engulf-clab-lab-registry

This plugin owns registry persistence and successful deploy/redeploy observation.
Consumers access it only through `engulf-clab-lab-registry-api`; they must never
read this plugin's state files directly. Publish records in `before_goal` before
consumers run, read the publication back to acknowledge invocations without a
consumer, and keep the API package's context name stable.

Never publish an Engulf capability. State handles are bound to the activation of
the callback that produced them, so a store placed in shared context is already
dead when a consumer reads it in its own callback. Load the snapshot and persist
pending updates from this plugin's own callbacks, exactly as Docker image
providers keep capability-free objects in shared context.

Keep registry transactions short and replace image IDs only with a complete
observation. Preserve prior topology and `ever_deployed` information on weaker
consumer observations. Destroy intentionally retains records. Do not scan lab
directories, measure consumption, mutate Docker, or make registry failure change
a completed goal result.

Packaging runs the registry before consumption and the schema compiler after
both. Test storage corruption, merge semantics, context publication, successful
and failed deployment handling, and Docker observation without requiring a live
daemon.

Validate narrowly with:

```bash
PYTHONPATH=plugins/engulf-clab-lab-registry-api/src:plugins/engulf-clab-lab-registry/src \
  .venv/bin/python -m pytest -q plugins/engulf-clab-lab-registry/tests
.venv/bin/python -m compileall -q plugins/engulf-clab-lab-registry/src
```
