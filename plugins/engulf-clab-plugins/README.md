# engulf-clab-plugins

`engulf-clab-plugins` is a shallow meta-package that installs every Engulf
plugin package maintained in this repository.

It does not publish an Engulf plugin entry point. Installing it activates the
plugins it depends on.

Current dependencies:

```text
engulf-clab-ensure-vrnetlab
engulf-clab-ensure-containerlab
engulf-clab-vrnetlab
engulf-clab-wan
```
