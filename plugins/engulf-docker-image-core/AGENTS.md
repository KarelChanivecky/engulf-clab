# Docker Image Core Instructions

- Do not import eclab, Containerlab, YAML, or application-specific providers.
- Keep provider calls side-effect free and Docker work in the scheduler.
- Preserve deterministic authority/priority/ID selection and recursive backtracking.
- Resolve every dependency from its own complete requirement; never copy
  parameters between image requirements.
- Execute every selected build recipe. Provider pull recipes refresh normally;
  the built-in fallback first accepts an existing local target and pulls only
  when it is missing.
- Execute archive recipes with `docker load` and retag from the references the
  load reports. Never pick a member of a multi-image archive implicitly, and
  never inspect the archive's format here.
- Keep the default pull offer low-authority and retry failed fallible offers
  without re-running provider callbacks.
- Acquire all tag leases on the callback thread and never pass APIs to workers.
- Use argv subprocess execution, reject recipe attempts to override file/tag/pull,
  and retain Docker output.
- Update API consumers and tests whenever graph semantics change.
