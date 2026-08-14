# engulf-clab-lab-writer

Renders deferred topology mutations into a temporary YAML file and replaces the
topology argument passed to Containerlab for `deploy`. Install it whenever a
plugin uses `engulf-clab-lab-parser` to mutate YAML; `engulf-clab-all-plugins` installs
both packages.

It has no user-facing YAML fields or environment variables. The original lab
file is never edited. During deploy, the collector writes a temporary
`.engulf-clab-lab-*.clab.yml` file beside the source topology, passes it with
`-t`, and removes it after the wrapped call. Keeping both files in the same
directory preserves Containerlab's resolution of relative paths. Plugins before
the collector record operations in the shared topology session; it resolves
delete precedence and applies modifications before additions.

This package is infrastructure for plugin authors, not a feature that lab
authors configure directly.
