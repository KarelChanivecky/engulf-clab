#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-${VENV_DIR:-$SCRIPT_DIR/../../.venv}/bin/python}"
exec "$PYTHON" -m build "$@" "$SCRIPT_DIR"
