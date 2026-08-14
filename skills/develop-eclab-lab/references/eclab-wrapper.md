# eclab

The `eclab` command, distributed by the `engulf-clab` package, wraps the
`containerlab` command and discovers
installed Engulf extensions for the `engulf_clab` application ID. It preserves
Containerlab command syntax while giving plugins lifecycle hooks before and
after the wrapped call.

## Install and run

```bash
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install engulf-clab engulf-clab-all-plugins

eclab deploy -t lab.clab.yml
eclab inspect -t lab.clab.yml
eclab destroy -t lab.clab.yml
```

The application itself does not require a fixed Containerlab installation path.
Install `engulf-clab-ensure-containerlab` to resolve an executable from an
explicit binary, a checkout, `PATH`, or a managed clone.

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

## Packaged container nodes

The optional `engulf-clab-containers` manager consumes declarative recipes from
independently installed collection plugins. Use
`eclab --eclab-containers-help` to list the active images. The maintained
`engulf-clab-containers-core` collection includes `host-connector`,
`ldap-389ds`, `proxy-node`, and `ubuntu-firefox-gui`. A host-connector example:

```yaml
topology:
  nodes:
    host-plug:
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

The additional core nodes provide 389 DS with Cockpit, Squid and Dante proxy
services, and a Firefox/XFCE desktop over noVNC. Their lab-specific addresses,
credentials, directory seed, certificates, and proxy policy remain topology
configuration rather than image defaults.

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
does not determine topology environment keys. Those derive from short product
metadata (or full product metadata when no short name is available):
`eclab` uses `ECLAB_*`, while a short product name of `vendor clab` uses
`VENDOR_CLAB_*`.

```python
from engulf_clab import CONTAINERLAB_APPLICATION

VENDOR_CLAB = CONTAINERLAB_APPLICATION.edition(
    display_name="vendor-clab",
    vendor="Vendor Networks",
    short_product_name="vendor clab",
    include_plugins={"com.example.vendor.containerlab"},
)
```

The edition launcher belongs in its own distribution and console-script entry
point. It should include its own plugin explicitly rather than publishing a
second shared `engulf_clab` application declaration.

## Library use

`ContainerlabApp` remains public for callers that need to customize the wrapper
goal, policy, state, completion, workspace, or diagnostics configuration.

```python
from engulf_clab import ContainerlabApp

app = ContainerlabApp()
```
