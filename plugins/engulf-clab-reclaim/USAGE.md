# Reclaim lab storage

Install `engulf-clab-reclaim` beside `engulf-clab`. The active plugin
adds:

```text
eclab reclaim [-t TOPOLOGY | --all [--stopped]]
eclab destroy [-t TOPOLOGY | --all] --reclaim
```

With no selector, eclab discovers exactly one topology in the current
directory. `-t`/`--topology` selects one topology relative to the invocation
directory. The topology selector and `--all` conflict, and `--stopped` requires
`--all`.

Reclaiming one lab permanently removes all its Containerlab containers, their
writable layers, and anonymous volumes. It then removes every available Docker
image used exclusively by that lab. Images that another known lab uses are
preserved.

`eclab destroy --reclaim` runs the normal destroy lifecycle first and then
reclaims the selected lab's Docker resources. Use `destroy --all --reclaim` to
plan every known lab before the bulk destroy and reclaim the complete image
union afterward. The reclaim step runs only after a successful destroy; a
failed or interrupted destroy leaves resources for a later explicit reclaim.

The command logs each successfully reclaimed container and image by ID. The
final status reports storage reclaimed in IEC units. For `destroy --reclaim`,
that amount covers the full destroy-and-reclaim operation, including storage
removed by the native destroy call. Standalone reclaim snapshots Docker's
reported aggregate storage for images, container writable layers, and local
volumes immediately before deletion; destroy snapshots it before native
destroy. Both compare that value with the value after every deletion attempt.
Build cache is excluded because reclamation does not remove it.
Concurrent Docker activity outside the reclamation lease can affect the
measured difference; an increase is reported as zero reclaimed. If the first
snapshot fails, no objects are deleted. If the final snapshot fails, completed
deletions remain in effect, the amount is reported as unavailable, and the
command exits nonzero.

Plain `reclaim --all` is guarded bulk cleanup: it fails without deleting
anything when any known lab still has a Containerlab container, running or
stopped. Once every known lab is destroyed, it reclaims all registry labs and
removes the complete union of their available images, including images shared
between them. `reclaim --all --stopped` instead selects only labs that have
containers and none of those containers are running. It removes those stopped
containers and every image with no owner outside that stopped selection;
images also owned by a running or destroyed lab are preserved. Destroyed and
running labs are not selected by this mode.

Image removal does not use Docker's `--force`. When one image ID has several
repository tags, reclaim removes those tags one at a time so Docker can remove
the image normally; Docker removes the corresponding digest references
automatically. Untagged images are removed by digest or ID. An image retained
by an unrelated container is still preserved by Docker and reported as a
failure.

The command never deletes the topology, startup configurations, captures, logs,
or any other file in a lab directory. It does not prune unrelated containers,
images, volumes, networks, or build cache. After complete success, selected labs
appear as `RECLAIMED` in consumption once unique image storage reaches zero.
Images shared with other labs may remain without changing that state.
Storage reclamation is deliberately Docker-only: it does not release non-Docker
resources owned by other plugins, such as host networking. The `destroy
--reclaim` form runs destroy first so those normal cleanup hooks still execute.

Before deleting Docker objects, the command stores complete selected-lab
observations through `engulf-clab-lab-registry-api`, and it deletes only after
`engulf-clab-lab-registry` has durably committed them. Planning and deletion run
in separate callbacks: `reclaim` records its intent and preempts the goal. For
`destroy --reclaim`, it records the intent before Containerlab runs and executes
reclamation in `after_goal` only after destroy succeeds. The registry owner
commits that intent in its own `after_goal` before reclamation executes. A
process killed between the commit and the deletions therefore leaves the
observations stored, and a new invocation sees them.

If the commit does not happen — the registry is unwritable, or it is unreadable
and cannot be preserved — reclamation aborts with a nonzero exit and issues no
delete requests at all. An unreadable registry stops the run before planning,
because a reclamation cannot preserve ownership it could not read.

A plan is fenced to the registry revision it was built from. When the registry
has not moved, the planned set is deleted unchanged. When it has moved, the plan
is re-validated against the committed records: an image that gained an owner
outside the selected labs is preserved and reported like other shared images,
and a selected lab whose committed record no longer matches the plan aborts the
run with no deletions, asking you to re-run `reclaim`. This is what keeps one
invocation from deleting an image another invocation registered meanwhile, and
keeps a stale flush from overwriting the other's record.

Container and image deletion is best effort: every requested object is
attempted and each successful removal is logged with its Docker ID. Failures are
logged, and the command exits nonzero if anything could not be removed. A
container or image that is already gone is treated as
success, so a retry after a crash mid-deletion neither fails spuriously nor
deletes anything extra. Successfully removed objects are not recreated when a
later deletion fails.

Docker access with permission to inspect and remove containers, anonymous
volumes, and images is required. The command serializes reclamation operations
with an Engulf lease. It does not require MCP, root when the configured Docker
endpoint is available to the caller, or any topology extension or
edition-specific key. Use the selected edition's launcher name in place of
`eclab`.

Review the target first with `eclab consumption` or `eclab consumption --all`.
`reclaim --all` is intentionally destructive and should be used only when every
known lab is already destroyed and all of its images may be rebuilt or pulled
again. Use `--all --stopped` when only currently stopped labs should be
reclaimed.

Useful troubleshooting checks are:

```bash
docker container ls --all --filter label=containerlab
docker image ls --all --no-trunc
eclab --engulf-plugin-list
```
