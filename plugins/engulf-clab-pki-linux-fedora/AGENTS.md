# Agent instructions

- Keep `PLUGIN_SCHEMA` at `audience=SchemaAudience.SUPPORT`: this plugin serves
  other plugins, so the generated lab skill omits it. Do not add topology
  controls, task routes, or node kinds to that declaration.
- Keep Fedora 44 first-class and derivatives best-effort.
- Install certificate-management prerequisites only; never install target applications.
- Package/network operations belong in `install`, never the runtime entrypoint.
