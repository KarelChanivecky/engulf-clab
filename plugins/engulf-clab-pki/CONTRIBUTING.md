# Contributing

When exporting user authorities into local scope, rebase topology trust and
private-authority references as well as manifest issuers. Test binding restored
node requests with an empty recipient user catalog; a populated catalog can hide
an accidental dependency on the producer's identities.

`catalog.py` owns strict YAML parsing, whole-object scope merge, reference
resolution, and cycle checks. `material.py` owns cryptographic generation and
immutable generation directories. `views.py` owns least-privilege staging;
`plugin.py` alone owns Engulf callbacks and topology mutation. `projections.py`
owns translation from resolved material and views into `engulf-clab-pki-api`
values. `freeze.py` is an optional freeze-API contributor and must not be
imported by the freeze package.

Resolve node requests, trust, mount targets, kinds, and inherited bind collisions
through the parser's `EffectiveNode`; do not maintain private inheritance rules.
Read materialized topology in preparation. Remove consumed controls using the
complete declaration-origin inventory, including shadowed/unused kind/group
definitions, before writer serialization. Manifest selection stays defaults-only.

Keep `analyze_call()` pure. All filesystem work belongs in `prepare_call()` and
must record attempt-created paths before later work can fail. Catch
`BaseException` inside preparation, because Engulf does not dispatch
`prepare_failed()` back to the plugin that raised. The callback-local rollback
must not reacquire an already-held lease; later-plugin rollback may acquire its
own lease if necessary. Never delete historical persistent state or recipient
global state.

Once the wrapped deploy or redeploy process starts, a nonzero exit may leave partial
containers consuming staged paths. Retain that attempt's views and provisioning
journal until successful `destroy`; only a pre-call/spawn failure can unwind them
immediately.

Global definitions cannot depend on local objects. Authority variants reuse the
authority identity and change only signing inputs. Fingerprint every complete
definition together with its resolved issuer identity; do not overwrite an old
generation. Inventory and freeze metadata must not contain key bytes, passwords,
or service credentials.

Only manifest v2 is accepted. Named certificate declarations live beside the
other catalogs; node binding lives exclusively in topology environment lists.
Resolve each list before duplicate checking, preserve whole-object shadowing,
and key leaf state by `(node, canonical declaration reference)`. Certificate
fields are fixed except for the documented omitted-CN node default; never add a
node-derived SAN. Build trust bundles from the resolved node trust set, not the
available public-authority catalog.

Service nodes are purely conditional and explicitly named. Keep generation-only
manifests free of service images and network behavior. EJBCA imports only the
default chain; alternate cross-sign variants remain static. Keep ML-DSA offline
until a supported transfer format exists.

Keep packaged service images on publicly pullable, explicit tags and cover
their exact references in tests. Do not use a removed or mutable `latest` tag
for the OpenLDAP directory recipe.

The implemented image-integration boundary is documented in
[`VRNETLAB_INTEGRATION.md`](VRNETLAB_INTEGRATION.md). PKI publishes authorized
typed paths without discovering consumers; image-family injectors translate
them, and vrnetlab owns guest installation. Preserve API immutability, canonical
ordering, identity IDs, and host/container path correspondence. Do not
fingerprint-deduplicate distinct named leaf declarations.

Run the narrow suites after changes:

```text
python -m compileall -q src
python -m pytest -q tests
python -m build --no-isolation
```

After schema, freeze, or documentation changes also run freeze tests,
`make check-skill`, installed plugin discovery/help, and `pip check`.
