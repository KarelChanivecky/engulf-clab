from __future__ import annotations

import subprocess
from pathlib import Path


def run(argv: list[str], cwd: Path | None = None) -> None:
    subprocess.run(argv, cwd=cwd, check=True)
