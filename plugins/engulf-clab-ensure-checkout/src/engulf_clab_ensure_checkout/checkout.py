"""Safe, reusable provisioning for a managed source checkout."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from engulf_api import StateStore

type CheckoutValidator = Callable[[Path], bool]
type CloneRunner = Callable[[Sequence[str]], None]
type Reporter = Callable[[str], None]


class CheckoutError(RuntimeError):
    """A configured or managed checkout could not be used safely."""


@dataclass(frozen=True, slots=True)
class CheckoutConfig:
    """Tool-specific names and defaults for a managed checkout."""

    label: str
    basename: str
    directory_env: str
    repository_env: str
    default_repository: str


def _run_clone(argv: Sequence[str]) -> None:
    try:
        subprocess.run(list(argv), check=True)
    except subprocess.CalledProcessError as error:
        raise CheckoutError(f"git clone failed with exit code {error.returncode}") from error


def ensure_checkout(
    state: StateStore,
    environ: Mapping[str, str],
    *,
    config: CheckoutConfig,
    is_valid: CheckoutValidator,
    info: Reporter,
    warning: Reporter,
    run_clone: CloneRunner = _run_clone,
) -> Path:
    """Return a configured or safely published user-scoped checkout."""
    configured = environ.get(config.directory_env, "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if is_valid(candidate):
            info(f"using {config.directory_env} checkout {candidate}")
            return candidate
        warning(f"ignoring invalid {config.directory_env}={configured}")

    target = state.path(config.basename)
    if is_valid(target):
        info(f"using managed {config.label} checkout {target}")
        return target.resolve()
    if target.exists() or target.is_symlink():
        raise CheckoutError(f"managed checkout exists but is invalid: {target}")

    repository = environ.get(config.repository_env, config.default_repository).strip()
    if not repository:
        raise CheckoutError(f"{config.repository_env} must not be empty")
    if shutil.which("git") is None:
        raise CheckoutError("missing required command: git")

    with tempfile.TemporaryDirectory(
        prefix=f".{config.basename}-clone-",
        dir=state.directory,
    ) as directory:
        staged = Path(directory) / "checkout"
        info(f"cloning {config.label} into managed Engulf state")
        run_clone(["git", "clone", "--", repository, str(staged)])
        if not is_valid(staged):
            raise CheckoutError(f"downloaded {config.label} checkout is invalid")
        try:
            staged.rename(target)
        except OSError as error:
            if is_valid(target):
                return target.resolve()
            raise CheckoutError(f"could not install managed checkout at {target}") from error

    return target.resolve()
