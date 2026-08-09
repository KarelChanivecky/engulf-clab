from __future__ import annotations

import os
from pathlib import Path

from engulf import Engulf

APPLICATION_ID = "engulf-clab"
CONTAINERLAB_BINARY = "containerlab"


def binary_path(binary: str = CONTAINERLAB_BINARY) -> str:
    """Return a configured Containerlab binary path or its PATH-resolved name."""
    if containerlab_dir := os.environ.get("CONTAINERLAB_DIR"):
        candidate = Path(containerlab_dir).expanduser() / binary
        if candidate.is_file():
            return str(candidate)
    return binary


def main() -> int:
    engulf = Engulf(binary_path(), application_id=APPLICATION_ID)
    return engulf.run()


if __name__ == "__main__":
    raise SystemExit(main())
