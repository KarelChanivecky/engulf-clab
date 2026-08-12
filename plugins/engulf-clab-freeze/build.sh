#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="${VENV_DIR:-${root}/.venv}"
python="${PYTHON:-python3.14}"
[[ -x "${venv_dir}/bin/python" ]] || "${python}" -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --upgrade build
"${venv_dir}/bin/python" -m build "${root}"
