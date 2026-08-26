#!/usr/bin/env bash
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$package_dir"
bootstrap_python="${PYTHON:-python3.14}"
venv_dir="${VENV_DIR:-$package_dir/.venv}"
venv_python="$venv_dir/bin/python"
if [[ ! -x "$venv_python" ]]; then "$bootstrap_python" -m venv --upgrade-deps "$venv_dir"; fi
if ! "$venv_python" -c 'import build' >/dev/null 2>&1; then
    "$venv_python" -m pip install 'build>=1.2,<2'
fi
exec "$venv_python" -m build "$@" .
