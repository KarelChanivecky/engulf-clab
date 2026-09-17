# engulf-clab-reclaim

Adds `eclab reclaim` and `eclab destroy --reclaim` to remove a lab's Docker
containers and reclaim its exclusively owned image storage while preserving the
lab workspace. It reports each reclaimed container and image plus the
Docker-measured reclaimed storage. `destroy --all --reclaim` plans every lab
before the bulk destroy and reclaims them afterward. Plain `reclaim --all`
still requires every lab to be destroyed; `--all --stopped` selects only stopped
labs.

See [USAGE.md](USAGE.md) for the operator contract and
[CONTRIBUTING.md](CONTRIBUTING.md) for implementation guidance.
