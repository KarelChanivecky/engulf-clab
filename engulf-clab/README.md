# engulf-clab

`engulf-clab` is an Engulf wrapper for Containerlab.

`CONTAINERLAB_DIR` may point at a directory containing a `containerlab` binary. If
that binary is absent, the wrapper falls back to resolving `containerlab` from
`PATH`.

Installed plugins are discovered through Engulf's application ID:

```text
engulf-clab -> engulf.plugins.v1.engulf_clab
```
