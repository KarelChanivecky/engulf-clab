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
| `eclab-containers.md` | Container manager README |
| `eclab-containers-core.md` | Core packaged-container collection README |
| `eclab-container-host-connector.md` | Packaged host connector container README |
| `eclab-container-ldap-389ds.md` | Packaged LDAP/389 DS container README |
| `eclab-container-proxy-node.md` | Packaged proxy container README |
| `eclab-container-ubuntu-firefox-gui.md` | Packaged Firefox GUI container README |
| `eclab-dockerfile-build.md` | Dockerfile builder README |
| `eclab-ensure-checkout.md` | Managed checkout helper README |
| `eclab-ensure-containerlab.md` | Containerlab resolver README |
| `eclab-ensure-vrnetlab.md` | vrnetlab resolver README |
| `eclab-vrnetlab-build.md` | vrnetlab image builder README |
| `eclab-license-pool.md` | License pool README |
| `eclab-wan.md` | Edition-aware DHCP WAN README |
| `eclab-lab-parser.md` | Shared topology parser README |
| `eclab-lab-writer.md` | Deferred topology writer README |
| `eclab-freeze.md` | Lab freeze README |

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
