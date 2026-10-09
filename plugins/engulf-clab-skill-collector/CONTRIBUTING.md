# Skill collector contributor notes

- Providers call `record_skill(api, absolute_path)` and package the complete
  directory. The directory basename is the stable installed name and must be
  unique among active contributions.
- Providers that publish paths in `before_goal()` declare a package ordering edge
  placing their postprocessing before this collector. A generated provider may
  publish from `after_goal()` and must also precede the collector there.
- `install-skills` is preempted from `analyze_call()` so all before-goal
  contributors and any strict compiler request complete before installation.
- Source fingerprints include every regular file's relative path and bytes.
  Symlinks, missing `SKILL.md`, unsupported names, and duplicate names fail the
  explicit install; automatic refresh logs and skips the unsafe contribution.
- Explicit installs validate every contribution and target before writing.
  Each replacement is atomic; a later filesystem failure can leave earlier
  completed targets installed. Automatic refresh is best effort and cannot
  alter the wrapped goal's result.
- Keep refresh writes atomic and scoped to collector-owned targets. A root tracks
  only skill names installed by an explicit command; newly contributed names are
  added on the next explicit command.
- Providers may mark unique generated source paths as temporary. The collector
  removes these after each copy/refresh attempt, even when the path is unused or
  the operation returns early. This prevents source snapshots accumulating in
  provider state; installed targets retain at most one recognized backup.

## Validation

```bash
.venv/bin/python -m compileall -q plugins/engulf-clab-skill-collector/src
.venv/bin/python -m pytest -q plugins/engulf-clab-skill-collector/tests
```
