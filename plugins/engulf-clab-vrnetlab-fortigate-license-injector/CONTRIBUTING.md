# Contributing

`plugin.py` is a narrow topology adapter. `analyze_call()` stays side-effect
free. In `prepare_call()`, read the typed license selection and the materialized
`TopologySession` after `engulf_clab.license_pool` has copied the selected file
into the lab. Do not use `LicenseSelection.source_path`: it names the pool
source, while the effective node's `license` field names the lifecycle-owned
copy that must remain available through destroy.

Resolve effective node kinds and inherited binds with `effective_nodes()`. Add a
read-only bind only for a selected `fortinet_fortigate` node. Reject any other
mount at `/tftpboot/appliance.lic`, and validate the selected copy as an
absolute, regular, non-symlink file before mutating the session. Keep paths out
of diagnostics and reports.

The license-pool and PKI plugins can both prepare the node's `binds` field. When
that field already exists, append through a list-index `TopologyEditor.add()`
operation so this plugin does not conflict with an earlier whole-list edit. If
the node has no direct `binds` declaration, add the new list at the leaf. Do not
replace the full list or discard inherited mounts.

Declare ordering in `pyproject.toml`: after the parser, license-pool, and PKI
plugins, before the topology writer and schema compiler. The PKI plugin can
also prepare `binds`; the explicit edge ensures its whole-list mutation exists
before this adapter appends its bind. Assert those entry points in the package
tests. This adapter owns no files, claims, leases, or cleanup.

Run:

```text
python -m compileall -q src
python -m pytest -q tests
python -m build --no-isolation
make check-skill
```
