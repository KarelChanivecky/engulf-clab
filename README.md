# engulf-clab monorepo

This repository contains the `engulf-clab` Containerlab wrapper application and
separately publishable Engulf plugin packages.

## Layout

```text
engulf-clab/   Wrapper application distribution
plugins/       One directory per plugin distribution
```

Current plugin packages:

```text
plugins/engulf-clab-ensure-checkout/    Shared managed-checkout support
plugins/engulf-clab-ensure-containerlab/ Containerlab binary provisioning
plugins/engulf-clab-ensure-vrnetlab/  Vrnetlab checkout provisioning
plugins/engulf-clab-plugins/          Meta-package that installs every plugin
plugins/engulf-clab-vrnetlab/         Pre-deploy vrnetlab image builds
plugins/engulf-clab-wan/              Forticlab-style managed DHCP WAN bridges
```

Plugins are discovered as installed Python packages. A plugin for this wrapper
should depend on `engulf-api` and `engulf-executable-wrapper-api`, derive from
`ExecutableWrapperPlugin`, and publish both declarations below with its exact
plugin ID as the entry-point name:

```text
engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper
engulf.plugins.v1.application.engulf_clab
```

The wrapper application imports the `engulf` runtime. Plugin packages should
import `engulf_api`, not `engulf`.

## Licensing

The monorepo is MIT licensed. Each plugin package should include its own MIT
`LICENSE` file using:

```text
Copyright (c) 2026 Karel Chanivecky
```
