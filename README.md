# engulf-clab monorepo

This repository contains the `engulf-clab` Containerlab wrapper application and
will contain separately publishable Engulf plugin packages.

## Layout

```text
engulf-clab/   Wrapper application distribution
plugins/       Future plugin distribution directories
```

Current plugin packages:

```text
plugins/engulf-clab-plugins/   Meta-package that installs every plugin
plugins/engulf-clab-wan/   Forticlab-style managed DHCP WAN bridges
```

Plugins are discovered as installed Python packages. A plugin for this wrapper
should depend on `engulf-api` and publish an entry point in:

```text
engulf.plugins.v1.engulf_clab
```

The wrapper application imports the `engulf` runtime. Plugin packages should
import `engulf_api`, not `engulf`.

## Licensing

The monorepo is MIT licensed. Each plugin package should include its own MIT
`LICENSE` file using:

```text
Copyright (c) 2026 Karel Chanivecky
```
