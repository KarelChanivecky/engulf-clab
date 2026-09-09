#!/usr/bin/env bash
set -euo pipefail

lab_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if (( $# == 0 )); then
    set -- deploy -t "$lab_root/all-features.clab.yml"
fi

exec eclab "$@"
