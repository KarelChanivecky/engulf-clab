#!/usr/bin/env bash
set -euo pipefail

lab_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime="$lab_root/local/runtime.env"
if [[ ! -f "$runtime" || -L "$runtime" ]]; then
    echo "error: missing regular runtime selection: $runtime" >&2
    exit 2
fi

# This file is generated exclusively by eclab-demo-lab-install.
source "$runtime"
: "${ECLAB_DEMO_FORTIGATE_IMAGE:?missing FortiGate image selection}"

if (( $# == 0 )); then
    set -- deploy -t "$lab_root/all-features.clab.yml"
fi

case "$1" in
    deploy|redeploy)
        exec eclab "$@" --eclab-vrnetlab-image "fgt=$ECLAB_DEMO_FORTIGATE_IMAGE"
        ;;
    *)
        exec eclab "$@"
        ;;
esac
