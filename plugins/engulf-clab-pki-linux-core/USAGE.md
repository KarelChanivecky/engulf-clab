# Linux PKI runtime

Distribution installers copy this runtime to `/opt/eclab-pki`. It discovers inventory v2 at
`ECLAB_PKI_ROOT`, installs all eligible client identities into detected browser stores, applies
per-program selectors, and then executes the original entrypoint. A missing mount is a no-op
unless `ECLAB_PKI_REQUIRED=true`. `ECLAB_PKI_SYSTEM_TRUST=augment|isolated` defaults to
`augment`; isolated mode points supported programs only at the projected bundle.

`ECLAB_PKI_IDENTITY_DEFAULT` is the non-browser fallback and
`ECLAB_PKI_IDENTITY_<PROGRAM>` overrides it. Browsers ignore the general default. Explicit
automatic browser selection uses `ECLAB_PKI_BROWSER_CLIENT_CERTS`; Firefox also supports
`eclab-pki-browser --browser firefox --identity REF`. Generated Playwright configuration is
published through `ECLAB_PKI_PLAYWRIGHT_CLIENT_CERTIFICATES` and can be loaded with the
packaged `playwright-helper.js`.

For detected Chrome/Chromium, the runtime imports every selected anchor from
`$ECLAB_PKI_ROOT/trust/ca-bundle.pem` into the startup user's `~/.pki/nssdb` and
`$XDG_DATA_HOME/pki/nssdb` (`~/.local/share/pki/nssdb` by default). Chromium reads the first
when it exists and the second otherwise, and builds differ in which they pick, so both carry
the same trust. An image may instead point one path at the other with a link or a bind mount;
the runtime recognises the shared database by device and inode and writes it once.
Firefox uses
`/opt/eclab-pki/state/firefox/all`; the per-identity Firefox launcher applies the same trust
to its generated profile. These imports run after client identity imports and set NSS trust
to `CT,c,c`, including anchors selected through `ECLAB_PKI_TRUST_INCLUDE` that do not occur
in any client certificate chain. Incidental chain CAs are not granted trust. Browser trust
also works when the node has no client identities; `certutil` is required for trust and
`pk12util` is additionally required for identity import. Distribution installers supply both.

Browser trust is augmented in both system-trust modes; `isolated` does not disable browser
built-in roots. Each managed database stores `eclab-pki-ca-bundle.pem` to track the trust this
runtime grants. Startup reconciles changed selections, clears trust for removed anchors,
and preserves client identities and unrelated certificates. Keep that file with its database
so later startups can reconcile removed anchors or interrupted imports. Trusting an inspection
CA allows that CA to authenticate intercepted HTTPS connections in these browser profiles.

After updating the runtime, rebuild dependent client images and recreate affected containers.
Reopen browsers after startup updates their databases. Verify the selected anchors have
`CT,c,c` with `certutil -L -d "sql:$HOME/.pki/nssdb"`,
`certutil -L -d "sql:${XDG_DATA_HOME:-$HOME/.local/share}/pki/nssdb"`, and
`certutil -L -d sql:/opt/eclab-pki/state/firefox/all`. Test both original and inspection-issued
HTTPS chains; launch Firefox with `--profile /opt/eclab-pki/state/firefox/all` to use its
managed store. If curl trusts a server but the browser reports an unknown authority, check
the resolved bundle, the browser's user/profile, and the NSS trust flags. A manually launched
browser under a different user or Firefox profile does not use these managed databases.

When curl has a selected identity, the runtime writes an owned `.curlrc` and exports
`CURL_HOME`, so ordinary curl invocations use the selected certificate and key. When nginx
has a selected identity, it writes `/opt/eclab-pki/state/nginx/identity.conf`, exports that
path as `ECLAB_PKI_NGINX_FRAGMENT`, and expects the consumer's TLS `server` block to include
the fragment. The fragment supplies the full certificate chain, key, and trusted chain; the
consumer continues to own listeners, names, routes, and application content.

CRL, OCSP, and managed certificate-database activation are reserved and fail explicitly; no
revocation enforcement is claimed.
