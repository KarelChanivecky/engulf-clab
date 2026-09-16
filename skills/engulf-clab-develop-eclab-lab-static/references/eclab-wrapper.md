# eclab

The `eclab` command, distributed by the `engulf-clab` package, wraps the
`containerlab` command and discovers
installed Engulf extensions for the `engulf_clab` application ID. It preserves
Containerlab command syntax while giving plugins lifecycle hooks before and
after the wrapped call.

## Contents

- [Install and run](#install-and-run)
- [Containerlab compatibility](#containerlab-compatibility)
- [Wrapper lifecycle](#wrapper-lifecycle)
- [Diagnostics and workspace identity](#diagnostics-and-workspace-identity)
- [Plugin discovery](#plugin-discovery)
- [Packaged container nodes](#packaged-container-nodes)
- [Freeze a shareable lab](#freeze-a-shareable-lab)
- [Editions](#editions)
- [Library use](#library-use)

## Install and run

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install engulf-clab engulf-clab-all-plugins

eclab deploy -t lab.clab.yml
eclab inspect -t lab.clab.yml
eclab destroy -t lab.clab.yml
```

The application itself does not require a fixed Containerlab installation path.
Install `engulf-clab-ensure-containerlab` to resolve an executable from an
explicit binary, a checkout, `PATH`, or a managed clone.

## Containerlab compatibility

eclab accepts ordinary Containerlab command names, flags, topology selection,
and exit codes. Its base topology language is Containerlab YAML; validate
standard structure against the upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
Plugin features are conventions expressed through valid `env`, `labels`,
`image`, `license`, and other Containerlab fields, not a replacement schema.

Arguments that belong to Engulf diagnostics or an active plugin are consumed by
the wrapper. The remaining effective argument vector is passed to Containerlab.
Use `--` when a downstream argument could otherwise be interpreted as a wrapper
control. Wrapper help includes Containerlab help plus active plugin help; this
means it reflects the launcher environment in which it runs.

Before authoring a lab for a particular installation, inspect:

```bash
eclab --help
eclab --engulf-plugin-list
```

Run every secondary discovery option advertised by a needed plugin, such as
`eclab --eclab-containers-help`. An absent help block means that plugin is not
active in that launcher. Install the package for base eclab or update the
edition's declared plugin set before using its controls.

## Wrapper lifecycle

`ContainerlabApp` builds an `ApplicationDefinition` around
`ExecutableWrapperGoal` and `PluginPolicy.declared()`. One accepted call follows
this order:

1. Engulf discovers and activates package entry points declared for the
   `engulf_clab` application.
2. Every adapter analyzes the immutable call. Analysis contributes arguments,
   environment, removals, or preemption but performs no external work.
3. If all analysis succeeds, plugins prepare in dependency order. They may
   acquire leases, prepare tools/images/host resources, and record deferred
   topology mutations.
4. The topology writer materializes mutations to a temporary file beside the
   original and substitutes its `-t` argument.
5. Containerlab runs and produces the wrapped outcome.
6. Postprocessing runs with the outcome so plugins can release or retain state
   safely. The writer attempts to remove its temporary topology in every case.

The source topology is not changed. A failed analyzer prevents preparation; a
preparation failure prevents Containerlab from starting and still allows
framework cleanup. Plugin ordering must be expressed with dependencies and
context declarations when correctness relies on another plugin.

## Diagnostics and workspace identity

Engulf options are consumed by the wrapper and never passed to Containerlab.

```bash
eclab --eclab-log-level INFO deploy -t lab.clab.yml
eclab --eclab-plugin-log-level .engulf_clab.wan=DEBUG deploy -t lab.clab.yml
```

The directory containing an explicitly selected topology is the canonical
workspace for plugin state. Therefore a `-t /labs/demo/lab.clab.yml` deployment
uses the same workspace when launched from any current directory. With no
filesystem topology, the current directory is the workspace.

## Plugin discovery

Install plugins as Python packages. They publish both of these entry points with
their exact plugin ID as the entry-point name:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
engulf.plugins.v1.application.engulf_clab
```

The companion `engulf-clab-all-plugins` package installs all maintained extensions;
individual feature packages can be installed instead for a smaller footprint.

`eclab --engulf-plugin-list` is supplied by the optional
`engulf-plugin-list` diagnostic extension. It reports each active plugin's
pre/post order, priority, source distribution, and installed version. It is a
useful first check for missing help, unexpected ordering, or an MCP service that
uses a different environment from the caller's shell.

Maintained topology mutators share `engulf_clab.topology.session`. The parser
loads one immutable source document for deploy, feature plugins record deferred
edits under their plugin IDs, and the writer resolves those edits once. This
prevents one plugin from observing another plugin's incidental file rewrite.

## Packaged container nodes

The optional `engulf-clab-containers` manager consumes declarative recipes from
independently installed collection plugins. Use
`eclab --eclab-containers-help` to list the active images. The maintained
`engulf-clab-containers-core` collection includes `host-connector`. A
host-connector example:

```yaml
topology:
  nodes:
    host-plug:
      kind: linux
      image: eclab.containers/host-connector
      env:
        ECLAB_CONNECT_HOST: "10.10.10.50;192.0.2.50"
  links:
    - endpoints: ["router:eth1", "host-plug:eth1"]
```

The connector keeps `eth0` for management and treats every other interface as
lab-facing. It forwards all protocols from each VIP to its external target over
the management network, with source NAT and per-interface reply steering. It
does not create a general WAN or DHCP service.


## Freeze a shareable lab

With `engulf-clab-freeze` installed, create a sanitized archive without changing
the source lab:

```bash
eclab freeze
```

Extract it and run `./run-eclab.sh`. License values are redacted and prompt the
recipient for their own file, pool, or environment variable at deployment time.
Use `eclab freeze --offline` to additionally bundle the active eclab virtual
environment, Containerlab, required vrnetlab sources, and local topology Docker
images other than generated vrnetlab appliances. It bundles the actual vrnetlab
checkout and leaves the vendor VM image for the recipient to select and supply.
Offline creation fails if any required component or ordinary image is missing;
the resulting platform-specific archive still expects compatible Docker and host
networking/QEMU facilities.
Freeze detects the single recognized topology in the current directory; use
`-t` / `--topology` to select one explicitly. Its default output is
`<lab-directory-name>.tar.gz` in the lab directory; use `--output` for another
destination. An interactive freeze asks before replacing an existing regular
archive. Earlier archive outputs in the lab are remembered in workspace state
and excluded from later freezes until removed.

## Editions

Edition launchers reuse the side-effect-free application definition while
providing a different command name and selected plugin set. The command name
does not determine topology label/environment keys: those are a fixed
`ECLAB_*` prefix, the same across every edition, never derived from product
metadata.

`short_product_name` is expected to stay `"eclab"` across every edition
instead. It is not used for labels; it namespaces the topology-local state
directory that plugins like `engulf-clab-freeze` and
`engulf-clab-license-pool` write beside a lab. Keeping it identical across
editions means their state converges on one shared directory rather than
fragmenting per edition. `display_name`, `vendor`, and `product` are what an
edition customizes for its own command-facing branding:

```python
from engulf_clab import CONTAINERLAB_APPLICATION

VENDOR_CLAB = CONTAINERLAB_APPLICATION.edition(
    display_name="vendor-clab",
    vendor="Vendor Networks",
    product="Vendor Containerlab",
    include_plugins={"com.example.vendor.containerlab"},
)
```

The edition launcher belongs in its own distribution and console-script entry
point. It should include its own plugin explicitly rather than publishing a
second shared `engulf_clab` application declaration.

Plugin `help()` must render the fixed `ECLAB_*` prefix, not derive one from
callback metadata — only the declared plugin catalog differs from base
eclab, not the label prefix.

## Library use

`ContainerlabApp` remains public for callers that need to customize the wrapper
goal, policy, state, completion, workspace, or diagnostics configuration.

```python
from engulf_clab import ContainerlabApp

app = ContainerlabApp()
```

The default `binary` is `containerlab`. Without an explicit customization, the
application resolver also honors `CONTAINERLAB_DIR/containerlab` when selecting
the initial executable; the ensure-containerlab plugin can subsequently make a
resolved binary available during preparation. Keep custom completion,
diagnostics, state, policy, workspace, and wrapper-goal objects stable for the
life of the created application and close the application after use.
