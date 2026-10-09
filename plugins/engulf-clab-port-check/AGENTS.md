# Plugin instructions

- Keep plugin ID `engulf_clab.port_check` and consume the parser's
  `engulf_clab.topology.session` context.
- Preserve preprocessing order: after `engulf_clab.lab_parser` and before
  `engulf_clab.lab_writer`. Declare CLI controls in `PLUGIN_SCHEMA`.
- Probe live host sockets by transport protocol. Saved ownership only supplies a
  likely running-lab name; it must never replace the live port check.
- Keep interactive and automatic remaps invocation-scoped, apply them through
  the topology editor, and persist ownership only after a successful deploy.
- Supported declarations and limitations are documented in `USAGE.md`; keep
  `CONTRIBUTING.md` aligned with callbacks, state, ordering, and ownership.
- This plugin declares no topology controls. Containerlab owns base topology
  syntax; see its upstream
  [topology schema](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
