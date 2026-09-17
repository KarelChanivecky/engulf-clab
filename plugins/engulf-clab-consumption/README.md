# engulf-clab-consumption

Adds `eclab consumption` for read-only CPU, RAM, lab-directory, and Docker
image-storage reporting. It can inspect one selected lab or every deployed and
indexed lab, including destroyed labs that still retain storage, with optional
two-second polling. Lab discovery history comes from the shared lab-registry
plugin. No-container labs are `STOPPED` while unique images remain and
`RECLAIMED` once unique image storage reaches zero; shared images may remain.
Image IDs are canonicalized before accounting, while Docker tags remain separate
image references.

See [USAGE.md](USAGE.md) for the operator contract and
[CONTRIBUTING.md](CONTRIBUTING.md) for implementation guidance.
