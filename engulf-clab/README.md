# engulf-clab

`engulf-clab` is an Engulf wrapper for Containerlab.

`CONTAINERLAB_DIR` may point at a directory containing a `containerlab` binary. If
that binary is absent, the wrapper falls back to resolving `containerlab` from
`PATH`.

Engulf supplies per-call diagnostic controls. For example,
`--engulf-clab-log-level INFO` enables informational messages, while
`--engulf-clab-plugin-log-level dev.karel.engulf_clab.wan=DEBUG` targets one
plugin. These wrapper options are removed before Containerlab is invoked.

## Releasing an edition

The package exports a side-effect-free application definition. A separately
released launcher can create an edition with its own command-facing name while
keeping the `engulf-clab` application identity, declared plugins, workspace state,
and leases:

```python
from engulf_clab import CONTAINERLAB_APPLICATION

VENDOR_CONTAINERLAB = CONTAINERLAB_APPLICATION.edition(
    display_name="vendor-clab",
    vendor="Vendor Networks",
    include_plugins={"com.example.vendor.containerlab"},
)


def main() -> int:
    with VENDOR_CONTAINERLAB.create() as application:
        return application.run()
```

The edition launcher should be its own distribution and console-script entry point.
Its plugin should publish its executable-wrapper goal declaration and be included
explicitly, rather than declaring the shared `engulf_clab` application entry point.

The vrnetlab topology environment prefix derives from the launcher name. The
official launcher uses `ENGULF_CLAB_VRNETLAB_TYPE` and
`ENGULF_CLAB_VRNETLAB_IMG_PATH`; the example edition uses
`VENDOR_CLAB_VRNETLAB_TYPE` and `VENDOR_CLAB_VRNETLAB_IMG_PATH`.
The official launcher still accepts the former `ECLAB_*` names for compatibility.

## Custom application instances

The reusable application class remains public for callers that need custom runtime
configuration without importing its console entry point:

```python
from engulf_clab import ContainerlabApp


class MyContainerlabApp(ContainerlabApp):
    pass
```

`ContainerlabApp` accepts executable-wrapper goal, plugin policy, completion,
workspace, state, and diagnostics configuration options. The `engulf-clab` command
itself is only a thin launcher for this class.

Installed executable-wrapper plugins are discovered through Engulf's goal catalog
and application declaration:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
engulf.plugins.v1.application.engulf_clab
```

For Engulf workspace state, the wrapper uses the directory containing the
Containerlab topology. Explicit file paths passed with `-t`, `--topo`, or
`--topology` therefore select the same workspace even when invoked from another
directory. Topology directories select themselves; URLs, `stdin`, and calls
without an explicit topology use the current directory.
