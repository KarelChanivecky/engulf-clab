#!/usr/bin/env bash
set -euo pipefail

lab_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
archive="$lab_root/artifacts/archive-source.tar.gz"

docker build --tag eclab-demo/archive-source:0.1 \
    --file "$lab_root/images/archive-source/Dockerfile" \
    "$lab_root/images/archive-source"
docker save eclab-demo/archive-source:0.1 | gzip -n >"$archive.tmp"
mv -- "$archive.tmp" "$archive"
echo "created $archive"
