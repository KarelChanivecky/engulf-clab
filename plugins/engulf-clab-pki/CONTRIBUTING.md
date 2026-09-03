# Contributing

`catalog.py` owns strict YAML parsing, whole-object scope merge, reference
resolution, and cycle checks. `material.py` owns cryptographic generation and
immutable generation directories. `views.py` owns least-privilege staging;
`plugin.py` alone owns Engulf callbacks and topology mutation. `projections.py`
owns translation from resolved material and views into `engulf-clab-pki-api`
values. `freeze.py` is an optional freeze-API contributor and must not be
imported by the freeze package.

Keep `analyze_call()` pure. All filesystem work belongs in `prepare_call()` and
must record attempt-created paths before later work can fail. Catch
`BaseException` inside preparation, because Engulf does not dispatch
`prepare_failed()` back to the plugin that raised. The callback-local rollback
must not reacquire an already-held lease; later-plugin rollback may acquire its
own lease if necessary. Never delete historical persistent state or recipient
global state.

Global definitions cannot depend on local objects. Authority variants reuse the
authority identity and change only signing inputs. Fingerprint every complete
definition together with its resolved issuer identity; do not overwrite an old
generation. Inventory and freeze metadata must not contain key bytes, passwords,
or service credentials.

Service nodes are purely conditional and explicitly named. Keep generation-only
manifests free of service images and network behavior. EJBCA imports only the
default chain; alternate cross-sign variants remain static. Keep ML-DSA offline
until a supported transfer format exists.

The implemented image-integration boundary is documented in
[`VRNETLAB_INTEGRATION.md`](VRNETLAB_INTEGRATION.md). PKI publishes authorized
typed paths without discovering consumers; image-family injectors translate
them, and vrnetlab owns guest installation. Preserve API immutability, canonical
ordering, fingerprint deduplication, and host/container path correspondence.

Run the narrow suites after changes:

```text
python -m compileall -q src
python -m pytest -q tests
python -m build --no-isolation
```

After schema, freeze, or documentation changes also run freeze tests,
`make check-skill`, installed plugin discovery/help, and `pip check`.
