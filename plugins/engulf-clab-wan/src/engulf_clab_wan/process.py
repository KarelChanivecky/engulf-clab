from __future__ import annotations

import subprocess
from pathlib import Path

from engulf_host_exec import root_command


def run(argv: list[str], cwd: Path | None = None) -> None:
    subprocess.run(root_command(argv), cwd=cwd, check=True)
