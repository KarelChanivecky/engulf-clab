# Plugin API instructions

- Keep this distribution limited to the immutable post-deployment instruction
  contract and invocation context.
- Preserve `INSTRUCTIONS_CONTEXT` and the tuple registry shape as public API.
- Contributors declare `INSTRUCTION_CONTEXTS` in both reads and writes; an
  `after_goal()` contributor must order before `engulf_clab.instructions`.
- The renderer alone owns output formatting and only displays entries after a
  successful deployment. This package must never execute contributed commands.
- Keep `USAGE.md` aligned with the public constructor and contribution ordering.
