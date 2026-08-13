# eclab MCP server

`engulf-clab-mcp` lets a local MCP client manage trusted `eclab` labs without
giving the client a general-purpose `sudo` path. It is deliberately a two-part
service:

```text
MCP host ── stdio ── eclab-mcp ── Unix socket ── eclab-mcpd (root) ── eclab
```

The bridge implements standard MCP stdio. The root daemon listens only on a
local Unix socket, so it has no HTTP or TCP endpoint.

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
sudo python3.14 -m venv /opt/eclab-mcp/venv
sudo /opt/eclab-mcp/venv/bin/python -m pip install 'engulf-clab-mcp[all-plugins]'
```

For the root daemon, install those commands into an administrator-owned location
(for example a root-owned virtual environment under `/opt/eclab-mcp/venv` or a
system Python location). The system installer rejects user-writable executable
trees, since a root service must never execute code from a normal user's venv.
Use a development venv for the unprivileged bridge and tests only.

For a checkout, `ENGULF_DIR=../engulf ./install-dev.sh` also builds and installs
the bridge into this repository's development virtual environment.

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
environment = { FORTIGATE_LICENSES = "/srv/eclab/licenses/fortigate" }
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

## MCP tools

The first release intentionally provides a narrow surface:

| Tool | Purpose |
| --- | --- |
| `eclab_list_labs` | Discover allowed topology IDs and profile names. |
| `eclab_validate` | Parse the topology and run an offline Containerlab graph validation. |
| `eclab_deploy` | Queue a complete `eclab deploy` operation. |
| `eclab_destroy` | Queue a complete `eclab destroy` operation for one lab. |
| `eclab_status` | Return normalized node state and status. |
| `eclab_node_logs` | Return bounded logs for a topology node. |
| `eclab_diagnostics` | Return bounded eclab, Containerlab, Docker, and plugin diagnostics. |
| `eclab_job_status`, `eclab_list_jobs`, `eclab_job_logs`, `eclab_job_cancel` | Observe and control queued work. |

Deploy and destroy are asynchronous and single-flight per lab. A second
lifecycle request for the same lab returns the active job ID. `destroy --all`,
node filtering, arbitrary flags, arbitrary executable paths, arbitrary command
execution, topology editing, and node command execution are not exposed.

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

## Operational notes

The service stores shared Engulf state at `/var/lib/eclab-mcp`, which makes
license-pool leases and managed state consistent across local agents. Job logs
and metadata are retained under `/var/log/eclab-mcp` and
`/var/lib/eclab-mcp/jobs`, respectively, with configured bounds and retention.

Members of `eclab-mcp` are trusted lab operators. In particular, writable lab
roots are privileged input because Containerlab topologies and enabled plugins
can create containers, networks, images, and lab-local files.

Remove only the systemd unit with `sudo eclab-mcp-uninstall-system`; its default
preserves configuration, job history, logs, and group membership. Add `--purge`
only when intentionally deleting all of that service data.
