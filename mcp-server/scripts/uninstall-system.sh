#!/usr/bin/env bash
# Remove the systemd unit while preserving configuration and state by default.
set -euo pipefail

purge=0

if [[ ${1:-} == "--purge" ]]; then
    purge=1
    shift
fi
if [[ $# -gt 0 || ${EUID} -ne 0 ]]; then
    echo "Usage: sudo uninstall-system.sh [--purge]" >&2
    echo "--purge also removes /etc/eclab-mcp, /var/lib/eclab-mcp, and /var/log/eclab-mcp." >&2
    exit 2
fi

systemctl disable --now eclab-mcpd.service 2>/dev/null || true
rm -f /etc/systemd/system/eclab-mcpd.service
systemctl daemon-reload

if [[ $purge -eq 1 ]]; then
    rm -rf /etc/eclab-mcp /var/lib/eclab-mcp /var/log/eclab-mcp
    echo "Removed service unit, configuration, state, and logs. The eclab-mcp group was retained."
else
    echo "Removed service unit. Configuration, state, logs, and the eclab-mcp group were retained."
fi
