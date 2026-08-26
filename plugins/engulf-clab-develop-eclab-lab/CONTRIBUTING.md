# Generated skill plugin development notes

- Derive from `SchemaBackedPlugin` so the install command and configuration-root
  path are completed directly from `PLUGIN_SCHEMA`.
- Keep the public distribution name `engulf-clab-develop-eclab-lab`; it is the
  stable package identity even though the plugin ID is product-neutral. The
  command `install-develop-eclab-lab-skill`, target `develop-eclab-lab`, and
  requested pipeline `eclab` are static.
- Gate registration, schema contribution, requests, tracked-target reads, and
  installation on the running application's normalized short product being
  exactly `eclab`. Another edition owns its own collector and must never cause
  this package to refresh the eclab target.
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
  Provider- and vendor-specific instructions belong in generated references,
  not the generic template.
- Validate with the schema API/generator tests and skill-creator quick validator
  against a generated temporary installation.

## Validation

Run the narrowest checks that exercise the changed boundary:

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-develop-eclab-lab/src
.venv/bin/python -m pytest -q plugins/engulf-clab-develop-eclab-lab/tests
make check-skill
```

Skill template or renderer changes require the `engulf-clab-schema` suite.

Use `./build.sh` in this directory for a distribution build, and `git diff --check`
before committing. Never run real deploy/destroy, Docker builds, Git clones, or
privileged MCP installation as part of validation.
