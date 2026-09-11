# Resource consumption plugin

This document records the accepted design implemented by the
`engulf-clab-consumption` package.

Status: implemented.

Distribution: `engulf-clab-consumption`.
Plugin ID: `engulf_clab.consumption`.

## Command and lab selection

```text
eclab consumption [-t topology] [--all] [-p]
```

| Invocation | Scope |
| --- | --- |
| `eclab consumption` | The lab in the current working directory. |
| `eclab consumption -t path/to/lab.clab.yml` | The lab identified by the selected topology. |
| `eclab consumption --all` | Every deployed lab visible through Docker plus every lab in the shared lab registry. |

Selection uses the existing topology-discovery convention for
the current directory, require `-t` when selection is ambiguous, and reject
`-t` together with `--all`. An explicit topology uses its containing directory
as the canonical lab workspace, regardless of the invocation directory.
`--all` discovers labs independently of the current directory. The separate
`engulf-clab-lab-registry` plugin remembers successful deploys/redeploys and
observations contributed through `engulf-clab-lab-registry-api`, so destroyed
labs remain discoverable. Labs destroyed before this feature must be queried
once with `-t` to seed the registry; no plugin recursively scans the filesystem.

## Consumption and output

Report consumption as a table with `LAB`, `STATE`, `CPU`, `RAM`, `LAB DIR`,
`IMAGES UNIQUE`, `IMAGES SHARED`, and `STORAGE` columns, one row per selected
lab, and a `TOTAL` row at the bottom. Include units in the output. A single-lab
query also includes the totals row.

`STATE` is `DEPLOYED` when at least one Docker container exists for the lab,
including when all its containers are stopped, and `UNDEPLOYED` otherwise.
The total row uses `—`. Stopped and undeployed labs report zero CPU and RAM.

- CPU: current aggregate CPU usage of the lab's running containers.
- RAM: current aggregate memory usage of the lab's running containers.
- STORAGE: the lab directory's storage size plus unique image storage plus
  shared image storage, with all three components shown separately.

CPU and RAM report measured use, rather than configured resource limits.
Lab-directory storage uses the canonical workspace, including generated files
inside it. Image storage comes from the images actually used by the deployed
lab; multiple nodes using the same image must not multiply that image's size
within the lab's row.

## Shared and unique image storage

The storage split is required in every report, including single-lab queries,
`--all`, and each `-p` polling refresh. An image's complete size is shared when
distinct known labs use the same image ID. Otherwise its complete size is
unique to its lab. Docker's daemon-wide shared-layer split is not used because
unrelated images on the daemon are outside the lab ownership comparison:

- `LAB DIR`: the lab directory's storage size.
- `IMAGES UNIQUE`: complete images used by only this lab.
- `IMAGES SHARED`: complete images used by multiple distinct labs.
- `STORAGE`: `LAB DIR + IMAGES UNIQUE + IMAGES SHARED` for that lab.

Classification uses every deployed and indexed lab, so filtering the displayed
report does not change an image's classification. Include an explicitly
selected stopped lab's image references when available. Multiple containers or
tags resolving to one image ID must not duplicate it within a lab. These
categories describe image footprints, not reclaimable disk space; retained
images and non-lab workloads may also reference the underlying layers.

If Docker no longer lists an image ID used by a retained container, estimate
that image's complete size from the container root filesystem minus its
writable layer. Use this only as a fallback for the missing image record. If
neither source supplies a size, propagate `N/A` rather than a partial result.
For an undeployed lab, the index retains the image IDs from its last successful
deploy or redeploy. An indexed ID that Docker confirms is absent contributes
zero because neither an image nor a container retains its storage. Docker
measurement failure remains `N/A` and must not be mistaken for confirmed
absence.

The `TOTAL` row counts each identical image ID once across the displayed labs.
Consequently, the total can be lower than the sum of the per-lab values. Shared
layers belonging to different image IDs may still contribute to more than one
image footprint because the report classifies complete image IDs, not layers.
For example, if two labs use the same 4 GiB image ID:

| LAB | LAB DIR | IMAGES UNIQUE | IMAGES SHARED | STORAGE |
| --- | --- | --- | --- | --- |
| lab-a | 1 GiB | 2 GiB | 4 GiB | 7 GiB |
| lab-b | 1 GiB | 3 GiB | 4 GiB | 8 GiB |
| TOTAL | 2 GiB | 5 GiB | 4 GiB | 11 GiB |

This example omits CPU and RAM to illustrate storage accounting.

Docker's [`docker system df -v` documentation](https://docs.docker.com/reference/cli/docker/system/df/)
defines the complete image sizes used for this classification. If Docker does
not return an image size and no retained-container fallback is available, show
`N/A` for the affected breakdown rather than treating it as zero.

The implementation uses these accounting choices:

- CPU is Docker's instantaneous percentage, summed across running lab containers.
- RAM is Docker's current memory-usage value, summed across running lab containers.
- Directory sizing uses allocated bytes, does not follow symlinks, and counts a
  hard-linked inode once.
- Stopped deployed labs use their retained container image IDs. Never-deployed
  labs resolve explicit node image references when first queried.

## Polling

`-p` enables continuous polling every two seconds for any selection mode:

```bash
eclab consumption -p
eclab consumption -t path/to/lab.clab.yml -p
eclab consumption --all -p
```

Without `-p`, print one consumption table and exit. With `-p`, display the first
sample as soon as it is available and refresh the measurements and totals every
two seconds until interrupted with Ctrl-C. In `--all` mode, rediscover running
labs and reload the shared registry on each poll so deploy and destroy
transitions are reflected. Avoid overlapping polls and restore terminal state
when polling stops.

## Implementation and acceptance

Implement consumption as an independently publishable Engulf plugin and put
inventory ownership in independently publishable lab-registry and API packages.
Follow the repository's package, lifecycle, documentation, and schema contracts.
Declare the command and options in `PluginSchema` and expose them through runtime
help when the plugin is installed and active. Resource collection must not deploy
labs, provision images, or modify topology files. Consumption accesses inventory
only through the typed API. The registry plugin owns transactional user-state
persistence and successful deploy/redeploy observation; consumers may contribute
explicit queries and discovery of deployed labs.

Acceptance coverage includes selection, selector conflicts, multiple containers
or labs referencing the same image ID, separate unique/shared columns,
image-ID-deduplicated totals, unavailable Docker measurements, and two-second
polling with clean interruption. It also covers stopped-lab topology image
resolution, successful/failed deploy registry observation, destroyed labs,
corrupt state, and directory hard-link/symlink handling. Unavailable measurements
remain distinct from zero use and prevent a partial value from appearing as a
complete total.
