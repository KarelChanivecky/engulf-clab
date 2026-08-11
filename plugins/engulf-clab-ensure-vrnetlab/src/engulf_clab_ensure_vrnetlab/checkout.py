from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from engulf_api import StateStore
from engulf_clab_ensure_checkout import CheckoutConfig, CheckoutError, ensure_checkout as ensure

from .errors import EnsureVrnetlabError
from .logging import info, warning

DEFAULT_VRNETLAB_REPO = "https://github.com/srl-labs/vrnetlab.git"
VRNETLAB_CHECKOUT_BASENAME = "vrnetlab"

_CHECKOUT_CONFIG = CheckoutConfig(
    label="vrnetlab",
    basename=VRNETLAB_CHECKOUT_BASENAME,
    directory_env="VRNETLAB_DIR",
    repository_env="VRNETLAB_REPO",
    default_repository=DEFAULT_VRNETLAB_REPO,
)


def valid_vrnetlab_checkout(path: Path) -> bool:
    return path.is_dir() and (path / "common" / "vrnetlab.py").is_file()


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
