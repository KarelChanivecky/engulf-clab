# Host execution library

- This is a shared library, not a discoverable plugin. Keep it independent of
  Engulf runtimes, Containerlab and application metadata.
- Elevate individual argv commands only; never elevate the Python application.
- Resolve elevated executables before sudo resets PATH; retain venv symlinks.
- Preserve the caller's Docker endpoint and configuration. A remote endpoint,
  unavailable daemon or unknown context is not a reason to switch to root's daemon.
- Keep Make and its filesystem work unprivileged; scope Docker shims to the
  child environment and remove them even when a build fails.
- Mock sudo, Docker and effective UID in tests. Never run privileged operations
  during validation. See CONTRIBUTING.md and USAGE.md.
