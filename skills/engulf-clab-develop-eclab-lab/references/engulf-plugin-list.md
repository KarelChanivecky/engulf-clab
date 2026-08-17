# engulf-plugin-list

This package contributes the isolated `--engulf-plugin-list` diagnostic for the
Engulf executable-wrapper goal. It has no normal goal-plugin entry point and its
module is imported only inside Engulf's Linux Bubblewrap worker.

Install it into the same Python environment as an Engulf executable-wrapper
application:

```console
python -m pip install engulf-plugin-list
my-wrapper --engulf-plugin-list
```

Installed diagnostic discovery is enabled by default and is independent of
`PluginPolicy` and plugin-side application declarations. The package declares the
exact `org.engulf.executable-wrapper` goal/API-major catalog and trigger groups, so
it is available to every compatible wrapper application in that environment. An
application created with `discover_installed=False` does not discover it.

The report has two tables. “Normal goal plugins” shows each selected plugin's
one-based preprocessing and postprocessing positions, priority, elevation
requirement, stable ID, and observed source. “Diagnostic extensions” shows every
discovered diagnostic ID, triggers, distribution, version, and isolation
availability. Empty tables explicitly contain `(none)`.

The trigger matches only as an exact argument before the first `--`. These remain
ordinary wrapped-command arguments:

```console
my-wrapper -- --engulf-plugin-list
my-wrapper --engulf-plugin-list=value
```

When the diagnostic matches, normal invocation hooks, wrapper phases, and the child
executable do not run. One-time wrapper goal setup has already completed. The report
normally exits 0; if required Linux isolation is unavailable, Engulf keeps this
module unimported and rejects the declared trigger with framework exit 70.

The displayed source is observed provenance, not a trust verdict. Installed records
include distribution/version and target, directory records include the canonical
directory and target, and direct records include their target. Normal plugins still
run in-process with the wrapper application's full authority during ordinary calls;
only this diagnostic target uses the isolated worker.

See [diagnostic extension authoring](engulf-runtime.md#authoring-a-diagnostic-extension)
for the entry-point contract, sandbox requirements, available data, output rules,
and resource limits.

The top-level `engulf_plugin_list` package exports `PluginListDiagnostic` for testing
or reuse and the ready-made `diagnostic` instance used by both entry points. Normal
applications should rely on installed diagnostic discovery instead of importing the
instance themselves.
