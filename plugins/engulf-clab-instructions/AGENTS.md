# Plugin instructions

- Keep plugin ID `engulf_clab.instructions` and render only after successful
  deploy or redeploy completion.
- Read environment values from the shared parser session and honor the active
  application's short-product prefix for runtime help.
- Remove the control key from defaults, kinds, groups, and nodes in the derived
  topology before the lab writer serializes it; never edit the source topology.
- Combine topology entries with `engulf-clab-instructions-api` contributions.
  Contributors declare its context for reads and writes; an `after_goal()`
  contributor orders before this renderer through packaging metadata.
- Use callback-bound `api.logger` for output. Never run contributed commands or
  fetch URLs. Keep schema, help, usage, and contributor contracts aligned.
- Containerlab YAML remains the base topology language. See the upstream
  [topology schema](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
