# engulf-clab-reclaim

Adds `eclab reclaim` to remove a lab's Docker containers and reclaim its
exclusively owned image storage while preserving the lab workspace. It reports
the Docker-measured storage reduction after reclamation. `--all` requires every
lab to be destroyed before removing images shared between known labs; `--all
--stopped` selects only stopped labs.

See [USAGE.md](USAGE.md) for the operator contract and
[CONTRIBUTING.md](CONTRIBUTING.md) for implementation guidance.
