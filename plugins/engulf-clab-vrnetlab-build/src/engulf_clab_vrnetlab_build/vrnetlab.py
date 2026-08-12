from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from engulf_clab_ensure_vrnetlab import VRNETLAB_PATH_CONTEXT

from .errors import VrnetlabError

_TYPE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def vrnetlab_root(context_value: object | None) -> Path:
    if not isinstance(context_value, (str, Path)) or not str(context_value).strip():
        raise VrnetlabError(
            f"Engulf context {VRNETLAB_PATH_CONTEXT} does not contain a vrnetlab path"
        )

    root = Path(context_value).expanduser().resolve()
    if not root.is_dir():
        raise VrnetlabError(f"vrnetlab checkout does not exist or is not a directory: {root}")
    return root


def builder_directory(root: Path, builder_type: str) -> Path:
    components = builder_type.split("/")
    if len(components) != 2 or any(
        not component or _TYPE_COMPONENT.fullmatch(component) is None for component in components
    ):
        raise VrnetlabError(f"invalid ECLAB_VRNETLAB_TYPE {builder_type!r}; expected vendor/type")

    resolved_root = root.resolve()
    builder = (resolved_root / components[0] / components[1]).resolve()
    if not builder.is_relative_to(resolved_root):
        raise VrnetlabError(f"vrnetlab builder escapes checkout: {builder_type}")
    if not builder.is_dir() or not (builder / "Makefile").is_file():
        raise VrnetlabError(
            f"vrnetlab builder {builder_type} does not contain a Makefile under {root}"
        )
    return builder


def vrnetlab_fingerprint(root: Path) -> str:
    if (root / ".git").exists() and shutil.which("git") is not None:
        try:
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ).stdout.strip()
            diff = subprocess.run(
                ["git", "diff", "HEAD", "--binary"],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ).stdout
            dirty = f"+dirty:{hashlib.sha256(diff).hexdigest()}" if diff else ""
            return f"git:{revision}{dirty}"
        except subprocess.CalledProcessError:
            pass

    stat = root.stat()
    return f"path:{root.resolve()}:{stat.st_mtime_ns}"
