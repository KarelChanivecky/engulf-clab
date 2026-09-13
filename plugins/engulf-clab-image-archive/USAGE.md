# engulf-clab-image-archive

Registers a Docker image provider that creates a node's image by loading a saved
Docker image archive before `eclab deploy` or single-source `eclab redeploy`. A node opts in with
`ECLAB_IMAGE_ARCHIVE`, which names the archive file; the node `image` tag is the
reference the archive is loaded as. Help, other commands, and topologies
without an archive declaration register no requests.

Install with `python -m pip install engulf-clab-image-archive`; it is also
included in `engulf-clab-all-plugins`. Version 0.2.0 and later requires the
Engulf 1.2 plugin APIs used for packaging-declared dependency ordering and
preparation-failure cleanup.

## Configuration

```yaml
topology:
  nodes:
    router:
      image: example/router:1.0.0
      env:
        ECLAB_IMAGE_ARCHIVE: images/router.tar.gz
    switch:
      image: example/switch:dev
      env:
        ECLAB_IMAGE_ARCHIVE: images/vendor-bundle.tar.gz
        ECLAB_IMAGE_ARCHIVE_REF: vendor/switch:2026.08
        ECLAB_IMAGE_ARCHIVE_RELOAD: "true"
```

| Node `env` field | Meaning |
| --- | --- |
| `ECLAB_IMAGE_ARCHIVE` | Archive path; opts the node into archive-backed provisioning. |
| `ECLAB_IMAGE_ARCHIVE_REF` | Reference inside the archive to retag as the node `image`. |
| `ECLAB_IMAGE_ARCHIVE_RELOAD` | Boolean string; load on every deploy instead of accepting an existing local tag. |

The archive is a `docker save` stream and must be named `.tar`, `.tar.gz`,
`.tgz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, or `.txz`. A qcow2 or raw disk image is
not an image archive; build those with `engulf-clab-vrnetlab-build`.

Paths are absolute or relative to the topology file's directory, not the
invoking shell's current directory. Absolute paths resolve on the launcher or
service host and may cross a privileged MCP profile's filesystem boundary;
prefer topology-relative packaged inputs.

The `ECLAB` prefix is fixed across editions. The node `image` must resolve to a
literal Docker tag during the shared parser's eager Containerlab-compatible
environment expansion, so `${ROUTER_TAG}` and `${ROUTER_TAG:-dev}` are accepted
when they resolve. The same expansion applies to the archive path, so
`ECLAB_IMAGE_ARCHIVE: ${ROUTER_ARCHIVE}` selects a host-specific location
without editing the lab.

Because Containerlab node environment values are strings, quote the reload
marker as `"true"`. The accepted boolean spellings are `true`, `false`, `1`,
`0`, `yes`, `no`, `on`, and `off`.

## Provisioning behavior

The provider offers a load recipe at `PREFERRED` authority for the node's exact
image tag, ahead of the dispatcher's low-authority pull fallback. A failed load
is reported instead of falling back to a registry pull, because a public image
with the same tag would not be the archive the lab selected.

Loading is skipped when the tag already exists locally, so repeated deploys do
not re-read a large archive. Set `ECLAB_IMAGE_ARCHIVE_RELOAD` to a true value
when the archive is rewritten in place under a stable tag and every deploy must
pick up the new content.

Retagging follows the archive's contents. When the archive already carries the
node `image`, that reference is used directly. When it does not,
`ECLAB_IMAGE_ARCHIVE_REF` selects which loaded reference is tagged as the node
image; without it, a single-image archive is retagged and a multi-image archive
fails with the loaded count rather than choosing arbitrarily.

The dispatcher acquires a lease for the node image tag and for any selected
archive reference, so concurrent labs cannot load or retag the same Docker
identity at once. Loaded images and their tags remain after destroy; use
lab-specific or immutable tags when unrelated labs must not overwrite the same
Docker identity.

The selected archive requests are retained only for the current invocation.
They are cleared after Containerlab is attempted, or during preparation unwind
if a later plugin cannot prepare. This cleanup removes only in-memory provider
selection; it does not delete Docker images or tags.

Validation requires node `env` to be a YAML mapping, a supported archive suffix,
an existing archive file, a nonempty literal image tag, and a whitespace-free
literal archive reference. Analysis rejects a node that sets
`ECLAB_IMAGE_ARCHIVE_REF` or `ECLAB_IMAGE_ARCHIVE_RELOAD` without
`ECLAB_IMAGE_ARCHIVE`.

Treat archive contents as trusted lab input: loading an archive imports whatever
images, layers, and tags it contains into the host's Docker daemon under the
caller's authorization. Use archives produced by a source you control.

## Troubleshooting

- Run the selected launcher's `--help` and confirm the displayed prefix and the
  `engulf_clab.image_archive` block appear.
- Resolve paths from the topology directory; an archive missing at analysis time
  fails the call before Containerlab runs.
- Verify the file with `docker load --input <archive>` and compare the reported
  `Loaded image:` lines to the node `image` tag.
- Set `ECLAB_IMAGE_ARCHIVE_REF` when the load reports a count and no matching
  tag, or when a bundle carries several images.
- Set `ECLAB_IMAGE_ARCHIVE_RELOAD` to `"true"` when a rewritten archive is not
  picked up because the previous tag still exists locally.
- Use `--eclab-image-build-jobs 1` to serialize provisioning when several nodes
  load large archives at once.

## Runtime schema discovery

The plugin records its archive node variables and snapshots this packaged
`USAGE.md` during `before_goal`. Dispatcher controls and node-local image
parameters are declared by `engulf_clab.image_build`.
