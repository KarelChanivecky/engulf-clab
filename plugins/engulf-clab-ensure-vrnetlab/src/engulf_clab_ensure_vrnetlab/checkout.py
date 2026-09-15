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
    update_checkout,
)
from engulf_clab_ensure_checkout import ensure_checkout as ensure
from engulf_clab_schema_api import VrnetlabSourceHint

from .errors import EnsureVrnetlabError
from .logging import info, warning

DEFAULT_VRNETLAB_REPO = "https://github.com/KarelChanivecky/vrnetlab/tree/master"
VRNETLAB_CHECKOUT_BASENAME = "vrnetlab"

_CHECKOUT_CONFIG = CheckoutConfig(
    label="vrnetlab",
    basename=VRNETLAB_CHECKOUT_BASENAME,
    directory_env="VRNETLAB_DIR",
    repository_env="VRNETLAB_REPO",
    default_repository=DEFAULT_VRNETLAB_REPO,
)
_UPDATE_CONFIG = UpdateConfig(
    label="vrnetlab",
    update_env="VRNETLAB_UPDATE",
    version_env="VRNETLAB_VERSION",
)


def require_vrnetlab_dependencies() -> None:
    """Validate host commands needed to build and run vrnetlab node images."""
    missing = tuple(
        command
        for command in ("docker", "qemu-img", "qemu-system-x86_64")
        if shutil.which(command) is None
    )
    if missing:
        raise EnsureVrnetlabError(f"missing required command(s): {', '.join(missing)}")


def valid_vrnetlab_checkout(path: Path) -> bool:
    return path.is_dir() and (path / "common" / "vrnetlab.py").is_file()


def vrnetlab_source_hint(
    state: StateStore,
    environment: Mapping[str, str],
) -> VrnetlabSourceHint:
    configured = environment.get("VRNETLAB_DIR", "").strip()
    if configured:
        checkout = Path(configured).expanduser().resolve()
        if valid_vrnetlab_checkout(checkout):
            return VrnetlabSourceHint(checkout=checkout)

    managed = state.path(VRNETLAB_CHECKOUT_BASENAME)
    if valid_vrnetlab_checkout(managed):
        return VrnetlabSourceHint(checkout=managed)

    repository = environment.get("VRNETLAB_REPO", DEFAULT_VRNETLAB_REPO)
    repository, embedded_revision = _split_repository_revision(repository)
    revision = environment.get("VRNETLAB_VERSION", "").strip() or embedded_revision or "HEAD"
    return VrnetlabSourceHint(repository=repository, revision=revision)


def resolved_vrnetlab_source(checkout: Path) -> VrnetlabSourceHint:
    return VrnetlabSourceHint(checkout=checkout.resolve(), resolved=True)


def _split_repository_revision(repository: str) -> tuple[str, str | None]:
    marker = "/tree/"
    if marker in repository and repository.startswith("https://github.com/"):
        base, revision = repository.split(marker, 1)
        if revision:
            return base, revision
    return repository, None


def _run(argv: Sequence[str]) -> None:
    try:
        subprocess.run(list(argv), check=True)
    except subprocess.CalledProcessError as error:
        raise EnsureVrnetlabError(f"git clone failed with exit code {error.returncode}") from error


def ensure_checkout(
    state: StateStore,
    environ: Mapping[str, str] | None = None,
) -> Path:
    current_env = environ if environ is not None else os.environ
    try:
        return ensure(
            state,
            current_env,
            config=_CHECKOUT_CONFIG,
            is_valid=valid_vrnetlab_checkout,
            info=info,
            warning=warning,
            run_clone=_run,
        )
    except CheckoutError as error:
        raise EnsureVrnetlabError(str(error)) from error


def update_vrnetlab(
    state: StateStore,
    checkout: Path,
    environ: Mapping[str, str] | None = None,
) -> bool:
    current_env = environ if environ is not None else os.environ
    try:
        return update_checkout(
            state, checkout, current_env, config=_UPDATE_CONFIG, info=info
        )
    except CheckoutError as error:
        raise EnsureVrnetlabError(str(error)) from error
