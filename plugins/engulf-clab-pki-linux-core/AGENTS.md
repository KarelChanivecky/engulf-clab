# Agent instructions

- Keep the runtime free of package and network operations.
- Touch only `/opt/eclab-pki` and integration-owned trust, browser, and application files.
- Treat inventory v2 and runtime application detection as authoritative.
- Never auto-select a browser certificate without an explicit origin rule.
- Apply only resolved bundle trust after identity imports in every NSS profile, including
  every Chromium database location and per-identity Firefox profiles. Preserve the owned-anchor
  journal and test real NSS chain validation, trust removal, identity preservation, and real
  headless browser loads without changing host browser stores.
