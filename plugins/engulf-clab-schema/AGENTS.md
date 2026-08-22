# Runtime schema generator development notes

- Plugin ID `engulf_clab.schema` is a terminal preprocessing dependency. Every
  contributor must run before it; do not replace dependency edges with priority.
- The selected checkout's working-tree schema is authoritative. Never replace it
  with an unrelated latest release schema.
- Normal refresh is best effort and cannot block Containerlab. Explicit schema
  requests are strict and must fail rather than claim stale output is current.
- Keep manifest, plugin YAML, and composed-schema serialization deterministic.
  Clone a referenced validation definition at most once per mutation location;
  never retain unreachable generated definitions or growing generated names.
- Plugin YAML is the agent-facing capability surface. Keep it compact, omit
  empty/default metadata, and leave the full JSON Schema self-contained for
  validators.
- Never expose credential-bearing repository URLs or absolute reference source
  paths.
- The generator imports only stable API packages, not Engulf runtime modules or
  another feature plugin implementation.
- Validate API tests, generator tests, ensure-containerlab tests, and the
  generated-skill consumer tests after changes.
