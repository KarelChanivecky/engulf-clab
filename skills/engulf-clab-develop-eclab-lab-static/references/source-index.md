# Bundled source index

These documentation and development-guidance snapshots are bundled into the
pip distribution at package-build time. They require no repository checkout.
Prefer runtime help for the installed feature set and a current local source
checkout when one is available; otherwise use these package-local files.

| Reference | Source |
| --- | --- |
| `engulf-api.md` | `engulf/engulf-api/README.md` |
| `engulf-runtime.md` | `engulf/engulf/README.md` |
| `engulf-development.md` | `engulf/AGENTS.md` |
| `executable-wrapper-api.md` | `engulf/engulf-executable-wrapper-api/README.md` |
| `executable-wrapper.md` | `engulf/engulf-executable-wrapper/README.md` |
| `engulf-plugin-list.md` | `engulf/plugins/engulf-plugin-list/README.md` diagnostic guide |
| `eclab.md` | `engulf-clab/README.md` repository overview |
| `eclab-development.md` | Root `AGENTS.md` repository guidance |
| `eclab-contributing.md` | Root contributor, validation, documentation, and release guide |
| `eclab-wrapper.md` | Wrapper distribution README |
| `eclab-mcp.md` | `engulf-clab/mcp-server/README.md` |
| `eclab-mcp-development.md` | MCP server `AGENTS.md` guidance |
| `eclab-mcp-config.md` | Complete root-owned MCP TOML configuration example |
| `eclab-all-plugins.md` | Aggregate plugin package README |
| `eclab-containers-api.md` | Container collection API README |
| `eclab-containers.md` | Container manager usage guide |
| `eclab-containers-core.md` | Core packaged-container collection usage guide |
| `eclab-container-host-connector.md` | Packaged host connector container usage guide |
| `eclab-container-wan-access.md` | Packaged WAN access container usage guide |
| `eclab-dockerfile-build.md` | Dockerfile builder usage guide |
| `eclab-ensure-checkout.md` | Managed checkout helper README |
| `eclab-ensure-containerlab.md` | Containerlab resolver usage guide |
| `eclab-ensure-vrnetlab.md` | vrnetlab resolver usage guide |
| `eclab-vrnetlab-build.md` | vrnetlab image builder usage guide |
| `eclab-license-pool.md` | License pool usage guide |
| `eclab-wan.md` | Edition-aware DHCP WAN usage guide |
| `eclab-lab-parser.md` | Shared topology parser usage guide |
| `eclab-lab-writer.md` | Deferred topology writer usage guide |
| `eclab-freeze.md` | Lab freeze usage guide |

## Development-guidance snapshots

| Reference | Source |
| --- | --- |
| `eclab-all-plugins-development.md` | Aggregate meta-package `AGENTS.md` |
| `eclab-containers-api-development.md` | Container collection API `AGENTS.md` |
| `eclab-containers-core-development.md` | Core collection `AGENTS.md` |
| `eclab-containers-development.md` | Container manager `AGENTS.md` |
| `eclab-dockerfile-build-development.md` | Dockerfile builder `AGENTS.md` |
| `eclab-ensure-checkout-development.md` | Managed checkout helper `AGENTS.md` |
| `eclab-ensure-containerlab-development.md` | Containerlab resolver `AGENTS.md` |
| `eclab-ensure-vrnetlab-development.md` | vrnetlab resolver `AGENTS.md` |
| `eclab-freeze-development.md` | Freeze plugin `AGENTS.md` |
| `eclab-lab-parser-development.md` | Topology parser `AGENTS.md` |
| `eclab-lab-writer-development.md` | Topology writer `AGENTS.md` |
| `eclab-license-pool-development.md` | License pool `AGENTS.md` |
| `eclab-vrnetlab-build-development.md` | vrnetlab builder `AGENTS.md` |
| `eclab-wan-development.md` | Managed WAN `AGENTS.md` |

The Engulf references are full public API/runtime guides, not summaries. Search
them for a symbol or concept before loading large sections into context.

Vendor-specific examples in upstream documentation are normalized to generic
router examples when copied into this skill.
