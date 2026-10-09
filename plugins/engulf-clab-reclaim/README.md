# engulf-clab-reclaim

Adds `eclab reclaim` and `eclab destroy --reclaim` to remove a lab's Docker
containers and reclaim eligible lab-owned image storage while preserving the
lab workspace. It reports each reclaimed container and image with lab
provenance and readable image references when available, plus measured storage.
`destroy --all --reclaim` plans every lab
before the bulk destroy and reclaims them afterward. Plain `reclaim --all`
still requires every lab to be destroyed; `--all --stopped` selects labs with
no running containers and stopped containers or recorded images still present
in Docker.

See [USAGE.md](USAGE.md) for the operator contract and
[CONTRIBUTING.md](CONTRIBUTING.md) for implementation guidance.
