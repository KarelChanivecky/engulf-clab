# Demo-lab package instructions

- This package installs resources; it is not an Engulf plugin.
- Keep `engulf-clab-wan` and `engulf-clab-develop-eclab-lab` absent from its
  dependencies and coverage.
- Preserve one source topology. Feature support files may accompany it, but do
  not split behavior into separate labs.
- Keep internal bridges namespaced below `segments`; a plain bridge requires a
  pre-existing host bridge.
- Never package FortiGate images or licenses. The installer asks for an external
  image and creates a truly empty license directory.
- Read `USAGE.md` and `CONTRIBUTING.md` before changing behavior.
