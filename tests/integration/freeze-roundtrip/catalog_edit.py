"""Noninteractive editor invoked only by `eclab pki global edit`."""

import json
import sys
from pathlib import Path

import yaml
from support import merge_catalog

if __name__ == "__main__":
    operation, additions, staged = sys.argv[1:]
    path = Path(staged)
    catalog = yaml.safe_load(path.read_text())
    updated = merge_catalog(
        catalog, json.loads(Path(additions).read_text()), remove=operation == "remove"
    )
    path.write_text(yaml.safe_dump(updated, sort_keys=False))
