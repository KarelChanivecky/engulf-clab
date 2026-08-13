# engulf-clab-all-plugins

Convenience meta-package that installs every maintained `engulf-clab` plugin:

```bash
python -m pip install engulf-clab engulf-clab-all-plugins
```

It does not publish an Engulf plugin itself. Its dependencies do, and Engulf
discovers those installed entry points when `engulf-clab` runs.

Included feature packages are Dockerfile builds, the packaged-container manager
and core collection, Containerlab and vrnetlab provisioning, vrnetlab image
builds, license pools, managed DHCP/NAT WAN bridges, frozen shareable archives,
and the topology mutation/collector infrastructure. Review the individual
package READMEs before enabling host-affecting features such as WAN bridges or
automatic source updates.

To keep an installation minimal, install `engulf-clab` and only the feature
packages a lab uses instead of this meta-package.
