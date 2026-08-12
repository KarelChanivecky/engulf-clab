#!/usr/bin/env bash
# Build and install this checkout plus a local Engulf checkout for development.
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
engulf_root="${ENGULF_DIR:-}"
venv_dir="${VENV_DIR:-${repository_root}/.venv}"
python_command="${PYTHON:-python3.14}"

if [[ -z "${engulf_root}" ]]; then
    echo "error: set ENGULF_DIR to the local Engulf checkout" >&2
    echo "example: ENGULF_DIR=../cliwrap ./install-dev.sh" >&2
    exit 2
fi
engulf_root="$(cd -- "${engulf_root}" && pwd)"
if [[ ! -x "${engulf_root}/build.sh" ]]; then
    echo "error: ENGULF_DIR must contain an executable build.sh: ${engulf_root}" >&2
    exit 2
fi

python_executable="${venv_dir}/bin/python"

if [[ ! -x "${python_executable}" ]]; then
    if "${python_command}" -c 'import ensurepip' >/dev/null 2>&1; then
        "${python_command}" -m venv --upgrade-deps "${venv_dir}"
    else
        "${python_command}" -m venv --without-pip "${venv_dir}"
    fi
fi

if ! "${python_executable}" -m pip --version >/dev/null 2>&1; then
    if "${python_executable}" -c 'import ensurepip' >/dev/null 2>&1; then
        "${python_executable}" -m ensurepip --upgrade
    elif "${python_command}" -m pip --version >/dev/null 2>&1; then
        pip_seed_args=(--python "${python_executable}" install)
        if compgen -G '/usr/share/python-wheels/pip-*.whl' >/dev/null; then
            pip_seed_args+=(--no-index --find-links /usr/share/python-wheels)
        fi
        pip_seed_args+=(pip)
        "${python_command}" -m pip "${pip_seed_args[@]}"
    else
        echo "error: ${python_command} provides neither ensurepip nor pip" >&2
        echo "install pip for Python 3.14, then rerun this script" >&2
        exit 1
    fi
fi

"${python_executable}" -m pip install --upgrade 'build>=1.2,<2' 'PyYAML>=6.0'

# Engulf owns its own build environment and validates its artifacts there.
"${engulf_root}/build.sh"

local_packages=(
    "plugins/engulf-clab-ensure-checkout"
    "plugins/engulf-clab-lab-parser"
    "plugins/engulf-clab-lab-writer"
    "plugins/engulf-clab-ensure-containerlab"
    "plugins/engulf-clab-ensure-vrnetlab"
    "plugins/engulf-clab-dockerfile-build"
    "plugins/engulf-clab-vrnetlab-build"
    "plugins/engulf-clab-wan"
    "plugins/engulf-clab-health-gates"
    "plugins/engulf-clab-license-pool"
    "plugins/engulf-clab-freeze"
    "plugins/engulf-clab-all-plugins"
    "engulf-clab"
)

for package in "${local_packages[@]}"; do
    PYTHON="${python_executable}" VENV_DIR="${venv_dir}" \
        "${repository_root}/${package}/build.sh"
done

install_wheel() {
    local package_dir="$1"
    local wheel_stem
    wheel_stem="$(
        "${python_executable}" -c \
            'import re, sys, tomllib; project = tomllib.load(open(sys.argv[1], "rb"))["project"]; name = re.sub(r"[-_.]+", "_", project["name"]); version = re.sub(r"[^A-Za-z0-9.]+", "_", project["version"]); print(f"{name}-{version}")' \
            "${package_dir}/pyproject.toml"
    )"
    local -a wheels=("${package_dir}/dist/${wheel_stem}-"*.whl)
    if [[ ${#wheels[@]} -ne 1 || ! -e "${wheels[0]}" ]]; then
        echo "error: expected one current wheel for ${package_dir}, found ${#wheels[@]}" >&2
        exit 1
    fi
    "${python_executable}" -m pip install --force-reinstall --no-deps "${wheels[0]}"
}

# Remove distributions superseded by the current package names. This also
# repairs development environments populated from stale dist/ artifacts.
"${python_executable}" -m pip uninstall --yes \
    engulf-clab-plugins \
    engulf-clab-dockerfile \
    engulf-clab-vrnetlab \
    engulf-clab-topology-collector \
    engulf-clab-topology \
    >/dev/null

engulf_packages=(
    "engulf-api"
    "engulf-executable-wrapper-api"
    "engulf-executable-wrapper"
    "engulf"
)
for package in "${engulf_packages[@]}"; do
    install_wheel "${engulf_root}/${package}"
done
for package in "${local_packages[@]}"; do
    install_wheel "${repository_root}/${package}"
done

"${python_executable}" -m pip check
"${python_executable}" -c \
    'from engulf_clab import CONTAINERLAB_APPLICATION; application = CONTAINERLAB_APPLICATION.create(); application.close()'

if [[ ! -x "${venv_dir}/bin/eclab" ]]; then
    echo "error: local install did not produce ${venv_dir}/bin/eclab" >&2
    exit 1
fi

echo "Installed local development eclab: ${venv_dir}/bin/eclab"
echo "Use: source \"${venv_dir}/bin/activate\""
echo "Or:  PATH=\"${venv_dir}/bin:\$PATH\" eclab --help"
