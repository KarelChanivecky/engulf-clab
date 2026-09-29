# Certificate-signed freeze archives

## Goal

Allow a producer to sign the final `.tar.gz` or `.tgz` output of `eclab freeze`
with a specified X.509 certificate and its private key. Allow a recipient to
require and verify that signature during `eclab defrost`, before the archive is
extracted or any archive-provided script, package, image, or contributor hook
can run. Keep signing optional so existing unsigned archives remain usable.

## Proposed interface

The names below are proposed, not implemented:

```bash
eclab freeze labs/demo --eclab-output share.tar.gz \
  --eclab-sign-cert producer.crt --eclab-sign-key producer.key
eclab defrost share.tar.gz --eclab-trust-cert trusted-producer.crt
```

Freeze writes a detached `share.tar.gz.sig` beside the archive. The signature
covers the exact bytes of the completed archive, including every mode's
topology, tools, wheelhouse, and image artifacts. The certificate may accompany
the signature for inspection, but defrost must take its trust anchor from a
recipient-specified file outside the archive. A certificate supplied only by
the archive proves no producer identity.

The first version should pin the signer to the supplied trusted certificate.
Certificate-chain validation, revocation, hardware-backed keys, and alternate
signature formats need separate design before they are advertised. Keep the
private key out of the archive, logs, state, and error text; support encrypted
keys through a secure prompt or an established key provider.

## Verification and compatibility

- `--eclab-trust-cert` requires the matching sidecar signature. Missing,
  malformed, mismatched, or untrusted signatures stop defrost before extraction
  or any recipient side effect. This prevents stripping the sidecar from
  silently downgrading a recipient that requested verification.
- A signed archive without a trusted certificate fails with a clear diagnostic;
  it is never treated as verified merely because it contains a certificate.
  Existing unsigned archives remain accepted when verification was not
  requested. Document the absence of authenticity verification in that path.
- Verify the signature over the archive bytes before opening the tar stream.
  Keep the existing archive safety and image checksum checks after signature
  verification; those checks serve different purposes.
- The generated `FREEZE-README.md` and public usage docs must show how to
  transfer the archive, sidecar, and trusted certificate, and how to verify
  before manual extraction or execution of a bundled launcher.
- Replacing an existing archive must handle its sidecar as one logical output:
  a failed freeze leaves the previous archive and signature usable, and a stale
  sidecar must never verify a new archive. Account for archive and sidecar name
  collisions and symlinks.

## Acceptance criteria

1. Sign and verify lean, runtime, and offline archives, including archives
   renamed between freeze and defrost. Recompression or one-byte modification
   makes verification fail.
2. Test missing signature, wrong trusted certificate, malformed signature,
   tampered archive, unsigned legacy archive, and interrupted replacement.
3. Confirm no extraction, environment initializer, contributor hook, image
   load, or runtime installation occurs after verification failure.
4. Keep the signer key out of the archive and diagnostic output. Document how
   recipients obtain and authenticate the trusted certificate independently.
5. Update plugin schema, dynamic help, `USAGE.md`, generated recipient guides,
   and tests together. Run the package's focused tests and `make check-skill`.
