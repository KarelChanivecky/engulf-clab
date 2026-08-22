# Generated skill plugin development notes

- The distribution name and plugin ID are product-neutral. Installed skill and
  command names derive only from callback-bound `short_product_name`.
- A valid explicit install request must enter the schema generator before the
  wrapped goal is preempted. The consumer installs only a compiled context value.
- Never overwrite an unrecognized or symlinked target. Stage beside the target,
  preserve fingerprinted runtime bundles, then rename atomically.
- Automatic refresh is best effort and cannot change a wrapped call's result.
  Explicit installation failures must return nonzero.
- Keep the skill entrypoint concise: read `current.json`, route through the
  catalog, load only relevant provider `schema.yaml` files, and open detailed
  references only as needed.
- Preserve durable cross-plugin lab judgment in the template. Append the
  generated catalog during installation and rewrite its artifact paths relative
  to the installed skill; never bake one runtime fingerprint into the template.
- Validate with the schema API/generator tests and skill-creator quick validator
  against a generated temporary installation.
