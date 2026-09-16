# eclab MCP server

`engulf-clab-mcp` lets a local MCP client manage trusted `eclab` labs without
giving the client a general-purpose `sudo` path. It is deliberately a two-part
service:

```text
MCP host ── stdio ── eclab-mcp ── Unix socket ── eclab-mcpd (root) ── eclab
```

The bridge implements standard MCP stdio. The root daemon listens only on a
local Unix socket, so it has no HTTP or TCP endpoint.

## Contents

- [Security model](#security-model)
- [Prerequisites](#prerequisites)
- [Install](#install)
- [Configure lab roots and profiles](#configure-lab-roots-and-profiles)
- [Service settings](#service-settings)
- [MCP tools](#mcp-tools)
- [Recommended agent workflow](#recommended-agent-workflow)
- [MCP client configuration](#mcp-client-configuration)
- [Jobs and cancellation](#jobs-and-cancellation)
- [Operations and troubleshooting](#operations-and-troubleshooting)
- [Upgrade and uninstall](#upgrade-and-uninstall)

## Security model

The MCP host never executes `eclab` as root itself. It starts the unprivileged
stdio bridge, which sends a versioned, length-bounded JSON request over a
group-protected Unix socket. The daemon accepts only enumerated methods and
constructs fixed argument vectors for configured absolute executables.

Lab paths cannot be supplied directly: clients discover a stable ID under an
administrator-approved root and pass that ID back. The daemon rediscovers it on
each request, rejects escaping symlinks, bounds topology size, and never decodes
an ID into an arbitrary path. It runs no shell and exposes no node execution,
arbitrary flags, arbitrary process IDs, TCP listener, or `destroy --all`.

Membership in the socket group is still privileged. A writable approved lab
root can contain Containerlab and plugin inputs that create containers,
networks, mounts, images, or host resources. Give group membership and write
access only to trusted lab operators.

## Prerequisites

- Linux with systemd and a local Unix socket;
- Python 3.12 or newer for the service virtual environment;
- absolute executable paths for `eclab`, `containerlab`, and `docker`;
- a root-owned service environment that normal users cannot modify;
- at least one existing, non-symlink topology root;
- at least one named invocation profile; and
- Docker/Containerlab privileges and any QEMU, Git, bridge, iptables, or image
  prerequisites required by the selected eclab plugins.

The installer validates command availability, but it cannot prove that every
lab's images, license pools, VM sources, network interfaces, or profile values
are correct. Use read-only diagnostics and validation after installation.

## Install

### One guided install from a checkout

The checkout includes a single user-facing installer. It builds the local
Engulf and eclab packages into a root-owned `/opt/eclab-mcp/venv`, installs the
systemd service, and collects its initial configuration in one flow:

```bash
ENGULF_DIR=../engulf ./install-mcp.sh
```

The wizard asks for:

- each trusted topology root;
- the local users allowed to access the MCP socket; and
- optional named profiles plus service-owned environment variables and secrets.

Secrets are entered with a hidden terminal prompt and the resulting
`/etc/eclab-mcp/config.toml` is mode `0600`. The installer validates that
Docker, Containerlab, and the service commands are available before it writes
the configuration or enables the service. It does not overwrite an existing
configuration.

For automation, avoid prompts and supply the authorization boundary directly:

```bash
ENGULF_DIR=../engulf ./install-mcp.sh --noninteractive \
  --lab-root labs=/srv/eclab-labs \
  --user "$USER"
```

`--venv /path` selects another protected service virtual environment and
`--no-start` is passed through when the service should be installed but not yet
started. Run `./install-mcp.sh --help` for all options.

### Installed-package setup

Install the package and the eclab application/plugins into the environment used
by the daemon. The `all-plugins` extra is convenient when labs use the complete
maintained plugin set.

```bash
sudo python3.12 -m venv /opt/eclab-mcp/venv
sudo /opt/eclab-mcp/venv/bin/python -m pip install 'engulf-clab-mcp[all-plugins]'
```

For the root daemon, install those commands into an administrator-owned location
(for example a root-owned virtual environment under `/opt/eclab-mcp/venv` or a
system Python location). The system installer rejects user-writable executable
trees, since a root service must never execute code from a normal user's venv.
Use a development venv for the unprivileged bridge and tests only.

For a checkout, `make build-engulf-clab-mcp` builds the bridge, and
`python -m pip install -e ./mcp-server` installs it into this repository's
development virtual environment.

The privileged service needs a root-owned configuration file and a group for
local lab operators. The supplied installer creates the `eclab-mcp` group,
installs the systemd unit, and can add users to that group:

```bash
sudo /opt/eclab-mcp/venv/bin/eclab-mcp-install-system --interactive

# Start a new login shell after group membership changes.
sudo systemctl status eclab-mcpd
```

The script never overwrites an existing `/etc/eclab-mcp/config.toml`. To avoid
the wizard, pass `--lab-root labs=/srv/eclab-labs --user "$USER"` instead.
Copy and edit [`config.toml.example`](etc/eclab-mcp/config.toml.example) first
when the standard paths do not apply. It expects `eclab`, `containerlab`, and
`docker` to already be installed at the configured absolute paths. From an
uninstalled source checkout, prefer `./install-mcp.sh`; the lower-level
`sudo mcp-server/scripts/install-system.sh --interactive` only installs and
configures an already-built service runtime.

## Configure lab roots and profiles

Only topology files beneath `[[lab_roots]]` are visible. MCP callers first use
`eclab_list_labs` and then pass the returned stable ID, such as
`labs:demo/lab.clab.yml`, to all other lab tools.

```toml
[service]
eclab_binary = "/usr/local/bin/eclab"
containerlab_binary = "/usr/bin/containerlab"
docker_binary = "/usr/bin/docker"

[[lab_roots]]
id = "labs"
path = "/srv/eclab-labs"

[profiles.default]
environment = { ROUTER_LICENSES = "/srv/eclab/licenses/router" }
secrets = { PRIVATE_REGISTRY_TOKEN = "replace-with-a-secret" }
```

The configuration is root-owned and must be mode `0600`. A
profile supplies service-side defaults and secret values. Callers may provide
ordinary application-variable overrides to deploy, destroy, status, logs, and
diagnostics, but cannot override runtime controls (`PATH`, Python/loader/XDG
settings, Engulf state, Containerlab/vrnetlab checkout controls, or the fixed
tool paths) or a profile secret. Environment values are passed without a shell
and are never included in job metadata or audit logs.

License-pool variable names referenced by `license: $POOL` and frozen-license
variables are profile-owned. This prevents a caller from making the root daemon
copy an arbitrary host file into a lab directory. Put pool paths and license
file choices in the selected profile instead. The same rule applies to a
vrnetlab image-source variable referenced by a topology; configure that source
path in the selected profile rather than sending it from an MCP client.

Lab-root and profile names use 1–64 letters, digits, underscores, or hyphens.
Discovery recognizes `*.clab.yml`, `*.clab.yaml`, `clab.yml`, `clab.yaml`,
`topology.yml`, and `topology.yaml`, skips common state/build directories, and
does not traverse symlinked directories. A returned ID is URL-safe and stable
for the root ID plus relative topology path, for example
`labs:demo/lab.clab.yml`. Always copy the returned ID; do not construct one from
an absolute filesystem path.

Profiles have two maps:

| Map | Purpose | Override behavior |
| --- | --- | --- |
| `environment` | Service-owned ordinary defaults such as pool or VM-source paths | A client may override a key only when it is not protected by runtime policy or topology-source policy. Prefer service ownership for privileged paths. |
| `secrets` | Registry tokens, credentials, and other sensitive values | Names and values are profile-owned and cannot be overridden by clients. Values are never returned or persisted in job metadata. |

Values must be strings with valid environment names, no control characters,
and at most 4096 encoded bytes. The daemon supplies `PATH`, home/XDG state,
locale, user identity, and `CONTAINERLAB_BIN` after merging the profile and
allowed caller values, so neither the service process environment nor callers
can replace those controls.

## Service settings

The complete example is `etc/eclab-mcp/config.toml.example`. All paths below
must be absolute; executable paths must already identify executable regular
files.

| `[service]` key | Default / bound | Meaning |
| --- | --- | --- |
| `socket_path` | `/run/eclab-mcp/eclab-mcp.sock` | Local daemon socket created for `socket_group`. |
| `socket_group` | `eclab-mcp` | Trusted local operator group. |
| `eclab_binary` | Required | Fixed launcher invoked for lifecycle, inspection, and plugin diagnostics. This may be an edition launcher. |
| `containerlab_binary` | Required | Fixed binary used for offline graph validation and version diagnostics. |
| `docker_binary` | Required | Fixed binary used for version and bounded node-log operations. |
| `state_dir` | `/var/lib/eclab-mcp` | Root home, XDG state/cache/config root, and durable job metadata parent. |
| `log_dir` | `/var/log/eclab-mcp` | Root-owned bounded job logs. |
| `runtime_path` | Standard system sbin/bin paths | Exact `PATH` passed to child operations. Include plugin prerequisites here. |
| `job_retention_days` | `14`; 1–3650 | Age after which completed job metadata and logs are pruned. |
| `max_job_log_bytes` | 2 MiB; 64 KiB–64 MiB | Per-job captured combined output. The daemon continues draining after truncation. |
| `max_rpc_frame_bytes` | 64 KiB; 1 KiB–1 MiB | Maximum request frame and response-budget basis for private socket RPC. |
| `max_read_output_bytes` | 64 KiB; 4 KiB–4 MiB | Per-stream bound for synchronous diagnostic/status commands. |
| `read_timeout_seconds` | `30`; 1–600 | Timeout for synchronous fixed subprocesses. |
| `cancel_grace_seconds` | `10`; 1–60 | Delay between terminating and force-killing a cancelled process group. |

The daemon requires the configuration to be a regular non-symlink file. When
running as root, it must be root-owned and mode `0600`. State and log directories
are root-owned mode `0700`; the socket installer manages group access at the
socket boundary.

## MCP tools

The service intentionally provides a narrow surface. Every result is an object
with `ok: true` plus `result`, or `ok: false` plus a stable error `code` and
safe `message`.

| Tool | Parameters | Result / effect |
| --- | --- | --- |
| `eclab_list_labs` | None | Allowed lab records and non-secret profile names. Parse errors are reported without exposing host paths. |
| `eclab_validate` | `lab_id` | Parses bounded YAML and runs `containerlab graph --offline --mermaid`; returns validity, name, nodes, bounded graph text, and truncation state. It does not run eclab plugins. |
| `eclab_deploy` | `lab_id`, `profile="default"`, optional `environment` | Queues exactly `<launcher> deploy -t <resolved-topology>` and returns a job record. |
| `eclab_destroy` | Same as deploy | Queues exactly one-lab destroy; no destroy-all or arbitrary flags. |
| `eclab_status` | Same identity/profile/environment parameters | Runs fixed eclab inspection and returns declared nodes plus normalized running-container state/status. |
| `eclab_node_logs` | `lab_id`, declared `node`, `tail_lines=200` (1–1000), profile/environment | Resolves the node through live inspection and returns a bounded Docker log tail. |
| `eclab_diagnostics` | Optional `lab_id`, profile/environment | Returns bounded eclab plugin-list, Containerlab version, Docker version, and optional lab status. |
| `eclab_job_status` | 32-character `job_id` | Returns retained public job metadata. |
| `eclab_list_jobs` | `limit=20` (1–100) | Returns newest retained jobs first. |
| `eclab_job_logs` | `job_id`, `tail_lines=200` (1–1000) | Returns bounded combined eclab output and truncation state. |
| `eclab_job_cancel` | `job_id` | Requests termination only for that known job's process group. A final job is returned unchanged. |

Deploy and destroy are asynchronous and single-flight per lab. A second
lifecycle request for the same lab returns the active job ID. `destroy --all`,
node filtering, arbitrary flags, arbitrary executable paths, arbitrary command
execution, topology editing, and node command execution are not exposed.

## Recommended agent workflow

1. Call `eclab_list_labs`. Copy a returned stable lab ID and choose only a
   profile name advertised in the same result.
2. Call `eclab_validate` before lifecycle work. Fix YAML, topology shape, node,
   link, or offline graph errors first. Validation proves base Containerlab
   structure, not plugin inputs, license availability, image availability, or
   host-network readiness.
3. Use `eclab_diagnostics` for a read-only view of the service's launcher,
   active plugins, Containerlab, Docker, and optional lab state. Do not rely on
   help or plugin discovery from a different local virtual environment.
4. Do not send profile-owned secrets, license-pool variables, frozen-license
   values, vrnetlab source variables, or protected runtime controls in caller
   overrides. Ask the administrator to configure them in the service profile.
5. Queue `eclab_deploy` or `eclab_destroy` only after explicit authorization.
   Save the returned job ID and poll `eclab_job_status` to `succeeded`, `failed`,
   or `cancelled`; use bounded job logs when it fails.
6. Use status and node logs only for existing runtime state. Do not infer deploy
   success from a queued response.

If a deploy request is rejected before returning a job, inspect the structured
error and diagnostics: it is a synchronous identity, profile, topology, or
environment-policy failure. If it returns a job and later fails, inspect job
status/logs: the fixed eclab operation reached the asynchronous execution path.

## MCP client configuration

Configure the local MCP host to launch the unprivileged bridge. For example:

```json
{
  "mcpServers": {
    "eclab": {
      "command": "/opt/eclab-mcp/venv/bin/eclab-mcp"
    }
  }
}
```

Use `eclab-mcp --socket /custom/path.sock` only for a deliberately custom local
installation. Normal users need membership in `eclab-mcp`; the bridge does not
need `sudo`.

The bridge accepts only `--socket ABSOLUTE_PATH`. A relative socket path exits
with status 2. The default must agree with the daemon's configured
`socket_path`; changing only the client does not relocate the daemon.

## Jobs and cancellation

Deploy and destroy jobs progress through `queued` and `running` to `succeeded`,
`failed`, or `cancelled`. The daemon permits one active lifecycle job per lab;
a conflicting request returns the active job ID instead of starting duplicate
host work. Jobs for different labs may run concurrently.

Metadata records the operation, stable lab ID, profile name, timestamps, local
peer UID/PID, state, exit code, safe message, cancellation flag, and truncation
flag. It deliberately omits argv and every environment value. Output is written
to a root-owned per-job log up to `max_job_log_bytes`; reads are independently
bounded.

Cancellation sends `SIGTERM` to the known child's process group and sends
`SIGKILL` after the configured grace period if it remains active. Cancellation
does not promise that eclab, Containerlab, Docker, or a plugin can roll back all
external work; inspect diagnostics and the lab status afterward. On daemon
restart, retained queued/running records become failed with an interruption
message rather than being silently resumed.

## Operations and troubleshooting

The service stores shared Engulf state at `/var/lib/eclab-mcp`, which makes
license-pool leases and managed state consistent across local agents. Job logs
and metadata are retained under `/var/log/eclab-mcp` and
`/var/lib/eclab-mcp/jobs`, respectively, with configured bounds and retention.

Members of `eclab-mcp` are trusted lab operators. In particular, writable lab
roots are privileged input because Containerlab topologies and enabled plugins
can create containers, networks, images, and lab-local files.

Useful administrator checks are:

```bash
sudo systemctl status eclab-mcpd
sudo journalctl -u eclab-mcpd
sudo stat -c '%U %G %a %n' /etc/eclab-mcp/config.toml
getent group eclab-mcp
```

After adding a user to the group, start a new login session so its supplementary
groups include `eclab-mcp`. If the bridge reports `service_unavailable`, check
the absolute socket path, daemon status, socket group/mode, current group
membership, and whether the bridge and daemon use the same protocol version.

If diagnostics cannot run a configured tool, verify the executable still
exists, remains executable, belongs to the protected service environment, and
has all helper commands available through `runtime_path`. If lab discovery is
empty, verify the root exists, topology filenames are recognized, no component
is a symlink, and the daemon can traverse the path. Invalid YAML appears in list
metadata and should be fixed before validation.

Do not edit job JSON, logs, Engulf state, or plugin lease state while the daemon
or a lifecycle job is active. Preserve them for diagnosis unless an explicit
purge is intended.

## Upgrade and uninstall

Upgrade the protected virtual environment as root, validate the existing
configuration against the new package, then restart the service. Keep the
bridge and daemon from the same package version so their private protocol agrees.
Re-run the installed system installer only when service files or paths need to
be refreshed; it deliberately preserves an existing configuration.

Remove only the systemd unit with `sudo eclab-mcp-uninstall-system`; its default
preserves configuration, job history, logs, and group membership. Add `--purge`
only when intentionally deleting all of that service data.
