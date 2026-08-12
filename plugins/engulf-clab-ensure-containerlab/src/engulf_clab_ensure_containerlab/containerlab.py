"""Containerlab-specific checkout validation and executable building."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from engulf_api import StateStore
from engulf_clab_ensure_checkout import (
    CheckoutConfig,
    CheckoutError,
    UpdateConfig,
    ensure_checkout,
    update_checkout,
)

from .errors import EnsureContainerlabError
from .logging import info, warning

DEFAULT_CONTAINERLAB_REPO = "https://github.com/srl-labs/containerlab.git"

_CHECKOUT_CONFIG = CheckoutConfig(
    label="Containerlab",
    basename="containerlab",
    directory_env="CONTAINERLAB_DIR",
    repository_env="CONTAINERLAB_REPO",
    default_repository=DEFAULT_CONTAINERLAB_REPO,
)
_UPDATE_CONFIG = UpdateConfig(
    label="Containerlab",
    update_env="CONTAINERLAB_UPDATE",
    version_env="CONTAINERLAB_VERSION",
)


def update_containerlab(
    state: StateStore,
    checkout: Path,
    environ: Mapping[str, str],
) -> bool:
    try:
        return update_checkout(
            state, checkout, environ, config=_UPDATE_CONFIG, info=info
        )
    except CheckoutError as error:
        raise EnsureContainerlabError(str(error)) from error


def executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def require_containerlab_dependencies() -> None:
    """Fail before a wrapped call when the Containerlab Docker dependency is absent."""
    if shutil.which("docker") is None:
        raise EnsureContainerlabError("missing required command: docker")


def valid_containerlab_checkout(path: Path) -> bool:
    return path.is_dir() and (path / "go.mod").is_file()


def find_repo_binary(checkout: Path) -> Path | None:
    for candidate in (checkout / "bin" / "containerlab", checkout / "containerlab"):
        if executable(candidate):
            return candidate
    return None


def _run(argv: Sequence[str], *, cwd: Path | None = None) -> None:
    try:
        subprocess.run(list(argv), check=True, cwd=cwd)
    except subprocess.CalledProcessError as error:
        raise EnsureContainerlabError(
            f"{' '.join(argv)} failed with exit code {error.returncode}"
        ) from error


def ensure_repo_binary(checkout: Path, *, rebuild: bool = False) -> Path:
    if not rebuild and (binary := find_repo_binary(checkout)):
        return binary
    if shutil.which("go") is None:
        raise EnsureContainerlabError("missing required command: go")

    output = checkout / "bin" / "containerlab"
    output.parent.mkdir(parents=True, exist_ok=True)
    info(f"building Containerlab from {checkout}")
    _run(("go", "build", "-o", str(output), "."), cwd=checkout)
    if not executable(output):
        raise EnsureContainerlabError(f"failed to build Containerlab binary at {output}")
    return output


def ensure_binary(
    state: StateStore,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve or safely provision a Containerlab executable."""
    current_env = environ if environ is not None else os.environ
    configured_binary = current_env.get("CONTAINERLAB_BIN", "").strip()
    if configured_binary:
        candidate = Path(configured_binary).expanduser().resolve()
        if executable(candidate):
            info(f"using CONTAINERLAB_BIN {candidate}")
            return candidate
        warning(f"ignoring invalid CONTAINERLAB_BIN={configured_binary}")

    configured_checkout = current_env.get("CONTAINERLAB_DIR", "").strip()
    if configured_checkout:
        candidate = Path(configured_checkout).expanduser().resolve()
        if valid_containerlab_checkout(candidate):
            info(f"using CONTAINERLAB_DIR checkout {candidate}")
            changed = update_containerlab(state, candidate, current_env)
            if changed:
                return ensure_repo_binary(candidate, rebuild=True)
            return ensure_repo_binary(candidate)

    if path_binary := shutil.which("containerlab"):
        resolved = Path(path_binary).resolve()
        info(f"using Containerlab from PATH: {resolved}")
        return resolved

    try:
        checkout = ensure_checkout(
            state,
            current_env,
            config=_CHECKOUT_CONFIG,
            is_valid=valid_containerlab_checkout,
            info=info,
            warning=warning,
            run_clone=lambda argv: _run(argv),
        )
    except CheckoutError as error:
        raise EnsureContainerlabError(str(error)) from error
    changed = update_containerlab(state, checkout, current_env)
    if changed:
        return ensure_repo_binary(checkout, rebuild=True)
    return ensure_repo_binary(checkout)
