# eclab

The `eclab` command, distributed by the `engulf-clab` package, wraps the
`containerlab` command and discovers
installed Engulf extensions for the `engulf_clab` application ID. It preserves
Containerlab command syntax while giving plugins lifecycle hooks before and
after the wrapped call.

## Contents

- [Install and run](#install-and-run)
- [Privilege](#privilege)
- [Shell completion](#shell-completion)
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

The package requires Engulf runtime `0.3` and executable-wrapper `0.3` or newer.
Those versions provide invocation normalization, trusted native completion
sourcing, and the elevated-startup gate used while constructing the eclab
application. Package resolution rejects older releases instead of allowing an
incompatible wrapper to fail during CLI startup.

The application itself does not require a fixed Containerlab installation path.
Install `engulf-clab-ensure-containerlab` to resolve an executable from an
explicit binary, a checkout, `PATH`, or a managed clone.

## Privilege

`eclab` refuses to start from a privileged process. Engulf requires each
application goal to opt into elevated startup through installed package
metadata; the shared `ExecutableWrapperGoal` deliberately has no such
declaration, and neither does anything in this repository. Running `eclab` as
root (or elevated on Windows) therefore fails before any plugin is loaded or
goal setup runs: the launcher prints the refusal on stderr and exits with the
Engulf framework error code (70).

This is a startup-consent gate, not a sandbox. Run `eclab` as an unprivileged
user and grant it access to the Docker socket or the specific host privileges
required by the Containerlab features you use. There is no command-line,
environment, or configuration override; adding an
`engulf.privilege_opt_in.v1.goal.v1` entry point would require a deliberate
contract change to the shared goal, not to this wrapper.

## Shell completion

Install schema-backed wrapper completion through eclab. The generated wrapper
prefers an already registered native Containerlab completer. If none is available,
eclab invokes its configured Containerlab executable as `completion <shell>`, sources
that trusted output once, and then merges the native and plugin candidates:

```bash
eclab install-completion bash
eclab install-completion zsh
eclab install-completion fish
```

Omit the shell to detect it from `SHELL`, or add `--output PATH`. Bash defaults
to `$XDG_DATA_HOME/bash-completion/completions/eclab`, Zsh to
`$XDG_DATA_HOME/zsh/site-functions/_eclab`, and Fish to
`$XDG_CONFIG_HOME/fish/completions/eclab.fish`. Ensure the Zsh directory is on
`fpath` before `compinit`; Bash and Fish use their conventional autoload paths.
Installation atomically refreshes Engulf-generated files and refuses symlinks
or unrelated existing content.

Completion combines the wrapped Containerlab completer with every active plugin's
schema declarations. It ignores Bash's generic `_minimal` fallback when deciding
whether native completion exists, and schema candidates still work if Containerlab
cannot provide a completion script. They include wrapper commands, global and
command-scoped flags, positional/literal values, and filesystem paths without loading
the compiled topology schema. Completion-script output executes in the interactive
shell, so eclab enables sourcing only for its trusted Containerlab executable.

## Containerlab compatibility

eclab accepts ordinary Containerlab command names, flags, topology selection,
and exit codes. Its base topology language is Containerlab YAML; validate
standard structure against the upstream
[`clab.schema.json`](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json).
Plugin features are conventions expressed through valid `env`, `labels`,
`image`, `license`, and other Containerlab fields, not a replacement schema.

Arguments that belong to Engulf diagnostics or an active plugin are consumed by
the wrapper. The remaining effective argument vector is passed to Containerlab.
Schema-declared wrapper flags paired with runtime environment variables are
normalized before workspace resolution and plugin callbacks. Environment
variables provide persistent defaults; CLI values win when both are present.
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
2. Registered environment-backed CLI options are consumed and overlaid on the
   immutable invocation environment.
3. Every adapter analyzes the immutable call. Analysis contributes arguments,
   removals, or preemption but performs no external work.
4. If all analysis succeeds, plugins prepare in dependency order. They may
   acquire leases, prepare tools/images/host resources, and record deferred
   topology mutations.
5. The topology writer materializes mutations to a temporary file beside the
   original and substitutes its `-t` argument.
6. Containerlab runs and produces the wrapped outcome.
7. Postprocessing runs with the outcome so plugins can release or retain state
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


## Freeze and defrost a shareable lab

With `engulf-clab-freeze` installed, create a sanitized archive without changing
the source lab:

```bash
eclab freeze
```

Extract it and run `./run-eclab.sh`. License values are redacted and prompt the
recipient for their own file, pool, or environment variable at deployment time.

```bash
eclab defrost demo.tar.gz --into labs/demo
```

`eclab defrost` is the receiving side: it expands one archive atomically,
removes the freeze metadata, restores launcher and bundled tool permissions,
prepares the runtime, points nodes at bundled Docker image archives carrying
their exact image, and answers the redacted licenses from `--license`,
`ECLAB_LICENSE_<NODE>`, `ECLAB_LICENSE`, or a prompt. The expanded lab holds
real license selections, so do not commit or re-share it.
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

`short_product_name` is not used for those portable topology keys. It names
topology-local state and the runtime schema pipeline. A launcher that only
changes branding may keep `"eclab"` and share base state and schema. A distinct
superset executable with its own generated skill uses a unique lowercase
hyphen-normalized value, registers a schema pipeline with `eclab` as its parent,
and therefore receives separate topology-local state and schema artifacts.
`display_name`, `vendor`, and `product` remain its command-facing branding:

```python
from engulf_clab import CONTAINERLAB_APPLICATION

VENDOR_CLAB = CONTAINERLAB_APPLICATION.edition(
    display_name="vendor-clab",
    vendor="Vendor Networks",
    product="Vendor Containerlab",
    short_product_name="vendor-clab",
    include_plugins={"com.example.vendor.containerlab"},
)
```

The edition's collector requests only `vendor-clab`; base eclab declarations
are inherited and expanded against the running edition metadata. The bundled
eclab skill collector is inactive under that executable, so the edition owns
its skill renderer, command, target, and refresh tracking.

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
the initial executable; the ensure-containerlab plugin can subsequently
make a CLI-selected resolved binary available during preparation. Set
`source_completion=False` only when a custom application must not source the trusted
binary's `completion <shell>` output. Keep custom completion,
diagnostics, state, policy, workspace, and wrapper-goal objects stable for the
life of the created application and close the application after use.
