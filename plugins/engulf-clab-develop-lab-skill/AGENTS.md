# Generated skill plugin development notes

- Derive from `SchemaBackedPlugin` so the edition-expanded install command and
  configuration-root path are completed directly from `PLUGIN_SCHEMA`.
- Keep the public distribution name `engulf-clab-develop-eclab-lab`; it is the
  stable package identity even though the plugin ID is product-neutral. Installed
  skill and command names derive only from callback-bound `short_product_name`.
- A valid explicit install request must enter the schema generator before the
  wrapped goal is preempted. The consumer installs only a compiled context value.
- Never overwrite an unrecognized or symlinked target. Stage beside the target,
  preserve fingerprinted runtime bundles, then rename atomically.
- Automatic refresh is best effort and cannot change a wrapped call's result.
  Explicit installation failures must return nonzero.
- Do not request automatic schema work without a tracked target. Report one
  current fingerprint only when every retained target is complete and identical;
  this lets the terminal generator suppress both compilation and target writes.
- Help-only and internal-completion invocations must not open target state or
  request schema generation.
- Keep the skill entrypoint concise: read `current.json`, route through the
  catalog, load only relevant provider `schema.yaml` files, and open detailed
  references only as needed.
- Preserve durable cross-plugin lab judgment in the template. Append the
  generated catalog during installation and rewrite its artifact paths relative
  to the installed skill; never bake one runtime fingerprint into the template.
- Validate with the schema API/generator tests and skill-creator quick validator
  against a generated temporary installation.
