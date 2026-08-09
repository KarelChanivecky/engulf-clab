from __future__ import annotations

import sys


def info(message: str) -> None:
    print(f"engulf-clab-wan: {message}", file=sys.stderr, flush=True)
