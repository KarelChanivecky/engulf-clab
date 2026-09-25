#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${FREEZE_TEST_PYTHON:-$here/../../../.venv/bin/python}" "$here/runner.py" lean "$@"
