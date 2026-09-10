# Resource consumption

Install `engulf-clab-consumption` beside `engulf-clab`, or install it through
`engulf-clab-all-plugins`. The active plugin adds this command:

```text
eclab consumption [-t TOPOLOGY | --all] [-p]
```

With no selector, eclab discovers exactly one topology in the current directory.
`-t`/`--topology` selects a topology relative to the invocation directory and
uses its parent as the canonical lab directory. `--all` reports every running
Containerlab lab visible to the current Docker daemon. The topology selector and
`--all` conflict.

The table contains `LAB`, `CPU`, `RAM`, `LAB DIR`, `IMAGES UNIQUE`,
`IMAGES SHARED`, and `STORAGE`, followed by `TOTAL`. CPU is the sum of Docker's
instantaneous container percentages, so a multi-core lab may exceed 100%. RAM is
Docker's current memory-usage value. Stopped selected labs report zero CPU and
RAM. The total is complete only when every contributing measurement is available.

`LAB DIR` is allocated filesystem space beneath the topology directory. The walk
does not follow symlinks and counts a hard-linked inode once. An unreadable path
is `N/A`. This intentionally includes generated files, captures, logs, and other
lab-owned content stored beneath that directory.

Image rows come from Docker's detailed disk-usage report. Docker defines an
image's virtual size as its unique size plus bytes shared with another image.
The plugin resolves deployed container image IDs and topology image references
(including inherited defaults and kind images) and counts an image ID once per
lab. When distinct running or explicitly selected labs use the same image ID,
its complete size is shared. Otherwise the report uses Docker's `UniqueSize` and
`SharedSize`, which also capture common layers between different images in the
daemon's image store. `STORAGE` is lab-directory bytes plus image virtual sizes.
The `TOTAL` row counts an identical image ID once across displayed labs; it does
not claim reclaimable bytes, and Docker may share layers with images outside the
displayed labs. A daemon that does not provide the detailed split produces `N/A`
rather than a guessed value.

`-p`/`--poll` takes a new sample every two seconds until Ctrl-C. It rediscovers
containers and labs each time. On a terminal it redraws the table; redirected
output receives successive tables separated by a blank line. Polls never overlap.

The command needs Docker CLI access equivalent to viewing container metadata,
statistics, image metadata, and system disk usage. It does not deploy, destroy,
pull, build, prune, or edit anything. Docker-access errors are fatal. Missing
image accounting or unreadable directories appear as `N/A`, and the note below
the table distinguishes unavailable values from zero use.

The plugin creates no files, persistent state, leases, or cleanup obligations.
It defines no topology extensions or edition-specific prefixes; the topology
remains ordinary [Containerlab YAML](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json),
and operators use the selected edition's launcher name in place of `eclab`.

Useful checks are:

```bash
docker container ls --filter label=containerlab
docker stats --no-stream
docker system df --verbose
eclab --engulf-plugin-list
```
