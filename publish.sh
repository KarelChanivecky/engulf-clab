#!/usr/bin/env bash

set -euo pipefail

if (( $# != 0 )); then
    echo "usage: $0" >&2
    exit 2
fi

: "${TWINE_REPOSITORY_URL:?Set TWINE_REPOSITORY_URL to the package upload endpoint}"

workspace_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
engulf_root="${ENGULF_DIR:-${workspace_root}/../engulf}"
engulf_root="$(cd -- "${engulf_root}" && pwd)" || {
    echo "error: Engulf checkout is unavailable: ${engulf_root}" >&2
    exit 2
}
state_dir="${engulf_root}/.pypi-repository"

normalize_url() {
    printf '%s/\n' "${1%/}"
}

if [[ -f ${state_dir}/repository-url ]] && \
    [[ $(normalize_url "${TWINE_REPOSITORY_URL}") == \
        $(normalize_url "$(<"${state_dir}/repository-url")") ]]; then
    [[ -f ${state_dir}/active ]] || {
        echo "error: the managed repository is not active" >&2
        exit 1
    }
    repository_status="$(
        docker container inspect \
            --format '{{ index .Config.Labels "org.engulf.package-repository" }} {{.State.Running}}' \
            engulf-package-repository 2>/dev/null
    )"
    [[ ${repository_status} == "managed true" ]] || {
        echo "error: the managed repository container is not running" >&2
        exit 1
    }
    [[ -f ${state_dir}/upload-token ]] || {
        echo "error: the managed repository upload token is missing" >&2
        exit 1
    }
    export TWINE_USERNAME="__token__"
    TWINE_PASSWORD=$(<"${state_dir}/upload-token")
    export TWINE_PASSWORD
    if [[ -f ${state_dir}/client-ca.pem ]]; then
        TWINE_CERT="${state_dir}/client-ca.pem"
        export TWINE_CERT
    fi
fi

exec make --directory "${workspace_root}" publish
