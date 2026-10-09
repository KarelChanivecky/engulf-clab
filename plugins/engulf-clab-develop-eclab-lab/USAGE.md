# Runtime-generated lab skill contribution

Install this contributor and the shared skill collector into the wrapper's
Python environment:

```bash
python -m pip install engulf-clab-develop-eclab-lab engulf-clab-skill-collector
eclab install-skills ~/.codex
```

The exact command is `eclab install-skills CONFIG_ROOT`. Pass the existing
configuration root that contains or will contain `skills/`, such as `~/.codex`,
not the `skills/` directory. The generated skill is installed at
`CONFIG_ROOT/skills/develop-eclab-lab/`. There are no environment-variable or
edition-prefix controls. This provider contributes only under the base eclab
short product; other editions can contribute their own skill paths.

The provider asks the installed schema compiler for the active eclab runtime
bundle, combines it with the concise packaged template, writes fingerprinted
references into a unique per-invocation directory beneath a process-owned
directory in its private user state, then contributes that directory by path.
The shared collector copies the directory and tracks the target. The shared
context carries a path rather than the generated catalog or reference contents.

The collector removes each temporary source tree after its installation or
refresh attempt, including early returns and handled failures. Unique source
directories let concurrent invocations copy independently. Process-exit cleanup
removes the process-owned directory; the next generation reaps roots left by
exited processes and legacy fingerprint snapshots older than a day. Process
roots over a day old are also reaped. The installed target
contains only the active runtime snapshot, and the collector keeps at most one
previous installed backup. The schema compiler retains only the active artifact
for each pipeline. Explicit installation errors return nonzero; later automatic
refresh is best effort and does not change the wrapped command result.

The collector requires an existing non-symlink configuration root. It refuses
symlinked source entries, `skills/` directories, targets, and unrelated targets
without an ownership marker. The skill content is trusted prompt instruction
data and will be loaded by the coding agent; install only trusted plugin
packages. No lab state or host resources are modified by installing this skill.

If `install-skills` is absent from `eclab --help`, install the collector in the
same environment as the launcher. If the target is reported as unrecognized,
inspect it and move it aside before retrying; the collector will not overwrite
unowned content.
