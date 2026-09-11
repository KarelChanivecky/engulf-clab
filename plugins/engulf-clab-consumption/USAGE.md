# Resource consumption

Install `engulf-clab-consumption` beside `engulf-clab`, or install it through
`engulf-clab-all-plugins`. The active plugin adds this command:

```text
eclab consumption [-t TOPOLOGY | --all] [-p]
```

With no selector, eclab discovers exactly one topology in the current directory.
`-t`/`--topology` selects a topology relative to the invocation directory and
uses its parent as the canonical lab directory. `--all` reports every deployed
Containerlab lab visible to Docker plus every lab remembered in the shared lab
registry. The topology selector and `--all` conflict.

The registry plugin records successful deploys and redeploys. Consumption
contributes explicit queries and `--all` discovery of existing containers. A lab
destroyed before this feature was installed must be queried once with `-t`
before it can appear in `--all`; the plugin does not recursively scan the
filesystem.

The table contains `LAB`, `STATE`, `CPU`, `RAM`, `LAB DIR`, `IMAGES UNIQUE`,
`IMAGES SHARED`, and `STORAGE`, followed by `TOTAL`. CPU is the sum of Docker's
instantaneous container percentages, so a multi-core lab may exceed 100%. RAM is
Docker's current memory-usage value. Stopped selected labs report zero CPU and
RAM. `STATE` is `DEPLOYED` when at least one lab container is running. Any
non-running lab that consumes unique image storage is `STOPPED`, whether its
containers still exist or it has no containers. Docker measurement uncertainty
also remains `STOPPED` rather than claiming that storage is zero. A lab becomes
`SLEEPING` when its unique image storage is zero. Shared image storage does not
prevent `SLEEPING`. The total row displays `—` for state.

`LAB DIR` is allocated filesystem space beneath the topology directory. The walk
does not follow symlinks and counts a hard-linked inode once. An unreadable path
is `N/A`. This intentionally includes generated files, captures, logs, and other
lab-owned content stored beneath that directory.

Image rows come from Docker's detailed disk-usage report. The plugin resolves
deployed container image IDs and topology image references (including inherited
defaults and kind images) and counts an image ID once per lab. An image's full
size is `IMAGES SHARED` when distinct running or explicitly selected labs use
the same image ID; otherwise its full size is `IMAGES UNIQUE`. Docker's
daemon-wide shared-layer values are deliberately not used because layers shared
with unrelated images do not represent storage shared between the reported
labs. `STORAGE` is lab-directory bytes plus image sizes. The `TOTAL` row counts
an identical image ID once across displayed labs and does not claim reclaimable
bytes.

A no-container lab uses the exact image IDs saved from its last
successful deploy or redeploy, so later tag movement does not change its
ownership. A never-deployed lab records the image IDs resolved by its explicit
query. If Docker confirms that a recorded no-container image ID is gone, it
contributes zero image bytes; a Docker measurement failure remains `N/A`.

An image can be removed or retagged while a container created from it remains
running. Docker then omits the old image ID from its image disk-usage report.
For that case the plugin asks container inspection for the retained root
filesystem size, subtracts its writable layer, and uses the result as the old
image's size. This is Docker's best remaining estimate and keeps the running
lab accountable after image cleanup. If neither measurement is available, the
affected image and storage values are `N/A` rather than a partial sum.

`-p`/`--poll` takes a new sample every two seconds until Ctrl-C. It rediscovers
containers and reloads the lab index each time. On a terminal it redraws the
table; redirected output receives successive tables separated by a blank line.
Polls never overlap.

The command needs Docker CLI access equivalent to viewing container metadata,
statistics, retained root-filesystem sizes, image metadata, and system disk
usage. It does not deploy, destroy,
pull, build, prune, or edit anything. Container-discovery errors are fatal.
Missing image accounting, container statistics, or unreadable directories
appear as `N/A`, and the note below the table distinguishes unavailable values
from zero use.

The consumption plugin creates no persistent state or leases. It accesses the
inventory only through `engulf-clab-lab-registry-api`; the registry plugin owns
transactional persistence and deploy/redeploy observation. Neither plugin
defines topology extensions or edition-specific prefixes; the topology remains
ordinary [Containerlab YAML](https://github.com/srl-labs/containerlab/blob/main/schemas/clab.schema.json),
and operators use the selected edition's launcher name in place of `eclab`.

Useful checks are:

```bash
docker container ls --filter label=containerlab
docker stats --no-stream
docker system df --verbose
eclab --engulf-plugin-list
```
