#!/usr/bin/env bash
# Remove development-installed Engulf and eclab distributions from one venv.
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="${VENV_DIR:-${repository_root}/.venv}"
python_executable="${venv_dir}/bin/python"

if [[ ! -x "${python_executable}" ]]; then
    echo "No development virtual environment at ${venv_dir}; nothing to uninstall."
    exit 0
fi

"${python_executable}" -m pip uninstall --yes \
    engulf-clab-mcp \
    engulf-clab-demo-lab \
    engulf-clab \
    engulf-clab-all-plugins \
    engulf-clab-develop-eclab-lab \
    engulf-clab-develop-lab-skill \
    engulf-clab-schema \
    engulf-clab-schema-api \
    engulf-clab-pki-api \
    engulf-clab-health-gates \
    engulf-docker-image-core \
    engulf-docker-image-api \
    engulf-clab-containers-pki \
    engulf-clab-containers-core \
    engulf-clab-containers \
    engulf-clab-containers-api \
    engulf-clab-plugins \
    engulf-clab-license-pool \
    engulf-clab-freeze \
    engulf-clab-lab-registry \
    engulf-clab-lab-registry-api \
    engulf-clab-reclaim \
    engulf-clab-consumption \
    engulf-clab-freeze-api \
    engulf-clab-pki \
    engulf-clab-pki-linux-fedora \
    engulf-clab-pki-linux-debian \
    engulf-clab-pki-linux-core \
    engulf-clab-vrnetlab-fortigate-pki-injector \
    engulf-clab-wan \
    engulf-clab-vrnetlab-build \
    engulf-clab-vrnetlab \
    engulf-clab-ensure-vrnetlab \
    engulf-clab-ensure-containerlab \
    engulf-clab-image-build \
    engulf-clab-dockerfile-build \
    engulf-clab-dockerfile \
    engulf-clab-lab-writer \
    engulf-clab-lab-parser \
    engulf-clab-topology-collector \
    engulf-clab-topology \
    engulf-clab-ensure-checkout \
    engulf \
    engulf-executable-wrapper \
    engulf-executable-wrapper-api \
    engulf-api \
    engulf-plugin-list \
    mcp

echo "Removed development eclab packages from ${venv_dir}."
echo "The virtual environment itself was kept; remove it manually if no longer needed."
