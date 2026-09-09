# Demo-lab package instructions

- This package installs resources; it is not an Engulf plugin.
- Keep `engulf-clab-wan` and `engulf-clab-develop-eclab-lab` absent from its
  dependencies and coverage.
- Preserve one source topology. Feature support files may accompany it, but do
  not split behavior into separate labs.
- Keep internal bridges namespaced below `segments`; a plain bridge requires a
  pre-existing host bridge.
- Keep the demo portable: it must not require a proprietary VM image, license,
  or local runtime-selection file.
- Read `USAGE.md` and `CONTRIBUTING.md` before changing behavior.
