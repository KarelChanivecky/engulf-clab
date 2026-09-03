# engulf-clab-pki

Lazy certificate-authority and node-certificate generation for `engulf-clab`.
A topology opts in explicitly, and the plugin mounts a private per-node view at
`/mnt/eclab/pki` or an explicitly selected absolute target. It publishes typed
authorized paths for optional image-family injectors but does not itself alter
guest trust stores or application settings.

Read [USAGE.md](USAGE.md) for the operator contract and
[CONTRIBUTING.md](CONTRIBUTING.md) for implementation and validation guidance.
