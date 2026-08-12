#!/usr/bin/env bash
set -euo pipefail

package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$package_dir"

bootstrap_python="${PYTHON:-python3.14}"
venv_dir="${VENV_DIR:-$package_dir/.venv}"
venv_python="$venv_dir/bin/python"

if [[ ! -x "$venv_python" ]]; then
    if "$bootstrap_python" -c 'import ensurepip' >/dev/null 2>&1; then
        "$bootstrap_python" -m venv --upgrade-deps "$venv_dir"
    else
        "$bootstrap_python" -m venv --without-pip "$venv_dir"
    fi
fi

if ! "$venv_python" -m pip --version >/dev/null 2>&1; then
    if "$venv_python" -c 'import ensurepip' >/dev/null 2>&1; then
        "$venv_python" -m ensurepip --upgrade
    elif "$bootstrap_python" -m pip --version >/dev/null 2>&1; then
        pip_seed_args=(--python "$venv_python" install)
        if compgen -G '/usr/share/python-wheels/pip-*.whl' >/dev/null; then
            pip_seed_args+=(--no-index --find-links /usr/share/python-wheels)
        fi
        pip_seed_args+=(pip)
        "$bootstrap_python" -m pip "${pip_seed_args[@]}"
    else
        echo "error: $bootstrap_python provides neither ensurepip nor pip" >&2
        echo "install pip for Python 3.14, then rerun this script" >&2
        exit 1
    fi
fi

if ! "$venv_python" -c 'import build' >/dev/null 2>&1; then
    "$venv_python" -m pip install 'build>=1.2,<2'
fi

exec "$venv_python" -m build "$@" .
