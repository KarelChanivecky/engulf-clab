# Agent instructions

- Preserve explicit topology opt-in and topology-relative selector resolution.
- Use shared EffectiveNode values for node controls and kinds; remove consumed
  controls at all declaration origins. Keep manifest selection defaults-only.
- Treat YAML as the sole catalog source of truth; malformed files fail closed.
- Preserve whole-object named merge and global-only resolution inside global definitions.
- Generate and stage only in deploy or single-source redeploy preparation and journal work. Unwind preparation and pre-spawn failures; retain views after a started deployment fails so partial containers remain safe until destroy.
- Never expose a CA key, leaf key, admin identity, passphrase, or service credential beyond its explicitly authorized node or encrypted export.
- Keep `ECLAB_PKI_MOUNT_TARGET` absolute, normalized, bind-safe, and removed from derived environments.
- Publish only immutable `engulf-clab-pki-api` projections after authorized views and mounts are ready; never discover or branch on consumers.
- Keep services independent and absent unless declared. Reject injected-node collisions.
- Keep freeze integration behind `engulf-clab-freeze-api`; ordinary archives contain no secrets and format-2 defrost remains atomic.
- Encrypted global-to-local export must rebase topology trust/private-authority requests along with manifest issuers. Verify it without the producer's global catalog.
- Update README, USAGE, CONTRIBUTING, schema help, tests, and generated skill together when behavior changes.
