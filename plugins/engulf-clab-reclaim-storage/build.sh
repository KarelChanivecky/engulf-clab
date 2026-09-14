#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="${PYTHON:-${VENV_DIR:-${root}/../../.venv}/bin/python}"
rm -rf -- "${root}/dist"
"${python}" -m build "$@" "${root}"
