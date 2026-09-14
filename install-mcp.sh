#!/usr/bin/env bash
# Install a root-owned local eclab MCP service from this checkout, then configure it.
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
engulf_root="${ENGULF_DIR:-${repository_root}/../engulf}"
service_venv="${ECLAB_MCP_VENV:-/opt/eclab-mcp/venv}"
python_command="${PYTHON:-python3.14}"
interactive=1
declare -a installer_arguments=()

usage() {
    printf '%s\n' \
        'Usage: ENGULF_DIR=/path/to/engulf ./install-mcp.sh [options]' \
        '' \
        'Builds and installs the local eclab stack into a root-owned virtual environment,' \
        'then creates the local-only MCP service and collects its initial configuration.' \
        '' \
        'Installer options:' \
        '  --engulf-dir PATH       Local Engulf checkout (default: ../engulf)' \
        '  --venv PATH             Root-owned service venv (default: /opt/eclab-mcp/venv)' \
        '  --python PATH           Python 3.14 command (default: python3.14)' \
        '  --noninteractive        Do not prompt; pass --lab-root and --user below' \
        '  -h, --help              Show this help' \
        '' \
        'All remaining options are passed to eclab-mcp-install-system, for example:' \
        '  --lab-root labs=/srv/eclab-labs --user alice --no-start' \
        '' \
        'Examples:' \
        '  ENGULF_DIR=../engulf ./install-mcp.sh' \
        '  ENGULF_DIR=../engulf ./install-mcp.sh --noninteractive \' \
        '    --lab-root labs=/srv/eclab-labs --user alice'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --engulf-dir)
            [[ $# -ge 2 ]] || { echo "error: --engulf-dir requires a path" >&2; exit 2; }
            engulf_root="$2"
            shift 2
            ;;
        --venv)
            [[ $# -ge 2 ]] || { echo "error: --venv requires a path" >&2; exit 2; }
            service_venv="$2"
            shift 2
            ;;
        --python)
            [[ $# -ge 2 ]] || { echo "error: --python requires a command" >&2; exit 2; }
            python_command="$2"
            shift 2
            ;;
        --noninteractive)
            interactive=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            installer_arguments+=("$1")
            shift
            ;;
    esac
done

if [[ "$service_venv" != /* || "$service_venv" == "/" || ! "$service_venv" =~ ^/[A-Za-z0-9._/+:-]+$ ]]; then
    echo "error: --venv must be a safe, non-root absolute path" >&2
    exit 2
fi

engulf_root="$(cd -- "$engulf_root" && pwd)" || {
    echo "error: Engulf checkout is unavailable: $engulf_root" >&2
    exit 2
}
if [[ ! -f "$engulf_root/engulf-api/pyproject.toml" || ! -f "$engulf_root/engulf/pyproject.toml" ]]; then
    echo "error: --engulf-dir must be an Engulf source checkout" >&2
    exit 2
fi

python_path="$(command -v "$python_command" || true)"
if [[ -z "$python_path" || "$python_path" != /* || ! -x "$python_path" ]]; then
    echo "error: --python must resolve to an executable Python 3.14 command" >&2
    exit 2
fi
if ! "$python_path" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))'; then
    echo "error: Python 3.14 is required for the eclab MCP service" >&2
    exit 2
fi

source_packages=(
    "$engulf_root/engulf-api"
    "$engulf_root/engulf-executable-wrapper-api"
    "$engulf_root/engulf"
    "$engulf_root/engulf-executable-wrapper"
    "$engulf_root/plugins/engulf-plugin-list"
    "$repository_root/plugins/engulf-clab-freeze-api"
    "$repository_root/plugins/engulf-clab-lab-registry-api"
    "$repository_root/plugins/engulf-clab-pki-api"
    "$repository_root/plugins/engulf-clab-ensure-checkout"
    "$repository_root/plugins/engulf-clab-lab-parser"
    "$repository_root/plugins/engulf-clab-lab-writer"
    "$repository_root/plugins/engulf-docker-image-api"
    "$repository_root/plugins/engulf-docker-image-core"
    "$repository_root/plugins/engulf-clab-containers-api"
    "$repository_root/plugins/engulf-clab-ensure-containerlab"
    "$repository_root/plugins/engulf-clab-ensure-vrnetlab"
    "$repository_root/plugins/engulf-clab-image-build"
    "$repository_root/plugins/engulf-clab-dockerfile-build"
    "$repository_root/plugins/engulf-clab-containers"
    "$repository_root/plugins/engulf-clab-containers-core"
    "$repository_root/plugins/engulf-clab-vrnetlab-build"
    "$repository_root/plugins/engulf-clab-wan"
    "$repository_root/plugins/engulf-clab-license-pool"
    "$repository_root/plugins/engulf-clab-freeze"
    "$repository_root/plugins/engulf-clab-lab-registry"
    "$repository_root/plugins/engulf-clab-reclaim"
    "$repository_root/plugins/engulf-clab-consumption"
    "$repository_root/plugins/engulf-clab-pki"
    "$repository_root/plugins/engulf-clab-pki-linux-core"
    "$repository_root/plugins/engulf-clab-pki-linux-debian"
    "$repository_root/plugins/engulf-clab-pki-linux-fedora"
    "$repository_root/plugins/engulf-clab-containers-pki"
    "$repository_root/plugins/engulf-clab-vrnetlab-fortigate-pki-injector"
    "$repository_root/plugins/engulf-clab-all-plugins"
    "$repository_root/engulf-clab"
    "$repository_root/mcp-server"
)
for package_dir in "${source_packages[@]}"; do
    if [[ ! -f "$package_dir/pyproject.toml" ]]; then
        echo "error: required source package is unavailable: $package_dir" >&2
        exit 2
    fi
done

as_root() {
    if [[ ${EUID} -eq 0 ]]; then
        "$@"
    else
        sudo -- "$@"
    fi
}

require_root_owned_tree() {
    local candidate="$1"
    while :; do
        local owner permissions
        owner="$(stat -c '%u' -- "$candidate")"
        permissions="$(stat -c '%a' -- "$candidate")"
        if [[ "$owner" != 0 || $((8#$permissions & 8#22)) -ne 0 ]]; then
            echo "error: the protected service environment must have a root-owned, non-writable path: $candidate" >&2
            exit 1
        fi
        [[ "$candidate" == "/" ]] && return
        candidate="${candidate%/*}"
        [[ -n "$candidate" ]] || candidate="/"
    done
}

parent_dir="$(dirname -- "$service_venv")"
echo "Creating or updating the protected MCP runtime at $service_venv"
as_root install -d -o root -g root -m 0755 "$parent_dir"
if [[ ! -x "$service_venv/bin/python" ]]; then
    as_root "$python_path" -m venv "$service_venv"
fi
if [[ -L "$service_venv" ]]; then
    echo "error: --venv must not be a symbolic link" >&2
    exit 1
fi
require_root_owned_tree "$service_venv"

service_python="$service_venv/bin/python"
if ! as_root "$service_python" -m pip --version >/dev/null; then
    as_root "$service_python" -m ensurepip --upgrade
fi

# Build backends and third-party runtime dependencies come from the configured
# package index. All project code below is installed from the two local checkouts
# without editing either checkout as root.
as_root "$service_python" -m pip install --upgrade \
    'hatchling>=1.27' \
    'mcp>=1.26,<2' \
    'PyYAML>=6.0'
as_root "$service_python" -m pip install --no-build-isolation --no-deps --upgrade --force-reinstall \
    "${source_packages[@]}"
as_root "$service_python" -m pip check

if [[ ! -x "$service_venv/bin/eclab" || ! -x "$service_venv/bin/eclab-mcp" || ! -x "$service_venv/bin/eclab-mcpd" ]]; then
    echo "error: service installation did not produce eclab, eclab-mcp, and eclab-mcpd" >&2
    exit 1
fi

if [[ $interactive -eq 1 ]]; then
    installer_arguments=(--interactive "${installer_arguments[@]}")
fi

echo "Installing the local eclab MCP service and collecting configuration."
as_root "$service_venv/bin/eclab-mcp-install-system" "${installer_arguments[@]}"
