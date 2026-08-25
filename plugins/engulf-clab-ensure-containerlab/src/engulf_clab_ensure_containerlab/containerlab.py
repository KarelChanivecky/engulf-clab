"""Containerlab-specific checkout validation and executable building."""

from __future__ import annotations

import os
import pwd
import shutil
import stat
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
from engulf_clab_schema_api import ContainerlabSourceHint, ContainerlabSourceKind

from .errors import EnsureContainerlabError
from .logging import info, warning

DEFAULT_CONTAINERLAB_REPO = (
    "https://github.com/KarelChanivecky/containerlab/tree/ft_fgt_license_support"
)

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


def sudoless_user() -> str:
    """Return the unprivileged account that requested sudo-less operation."""
    uid = os.getuid()
    if uid == 0:
        raise EnsureContainerlabError(
            "run the sudoless command as the user who needs access, not as root; "
            "the command invokes sudo when required"
        )
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError as error:
        raise EnsureContainerlabError(f"cannot resolve the current user for uid {uid}") from error


def enable_sudoless(binary: Path, username: str) -> None:
    """Root-own a safe executable mode and grant required group access."""
    if not executable(binary):
        raise EnsureContainerlabError(f"Containerlab binary is not executable: {binary}")
    if shutil.which("sudo") is None:
        raise EnsureContainerlabError("missing required command: sudo")

    # Establish both authorization boundaries before enabling SUID. ``-f``
    # makes group creation safe to repeat when package installation created it.
    _run(("sudo", "--", "groupadd", "-f", "-r", "clab_admins"))
    _run(("sudo", "--", "groupadd", "-f", "-r", "docker"))
    _run(("sudo", "--", "usermod", "-aG", "clab_admins,docker", username))
    # A user-owned SUID binary would not elevate Containerlab. Root ownership
    # also makes an exact 4755 mode important: never retain group/world writes.
    _run(("sudo", "--", "chown", "root:root", str(binary)))
    _run(("sudo", "--", "chmod", "4755", str(binary)))

    metadata = binary.stat()
    if (
        metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o4755
    ):
        raise EnsureContainerlabError(
            f"sudo-less setup did not leave {binary} root-owned with mode 4755"
        )


def valid_containerlab_checkout(path: Path) -> bool:
    return path.is_dir() and (path / "go.mod").is_file()


def find_repo_binary(checkout: Path) -> Path | None:
    for candidate in (checkout / "bin" / "containerlab", checkout / "containerlab"):
        if executable(candidate):
            return candidate
    return None


def source_checkout_for_binary(binary: Path) -> Path | None:
    candidate = binary.expanduser().resolve()
    for parent in (candidate.parent, *candidate.parents):
        if (parent / "go.mod").is_file() and (parent / "schemas").is_dir():
            return parent
    return None


def containerlab_source_hint(
    state: StateStore,
    environ: Mapping[str, str],
) -> ContainerlabSourceHint:
    configured_binary = environ.get("CONTAINERLAB_BIN", "").strip()
    if configured_binary:
        candidate = Path(configured_binary).expanduser().resolve()
        if executable(candidate):
            checkout = source_checkout_for_binary(candidate)
            return (
                ContainerlabSourceHint(
                    ContainerlabSourceKind.CHECKOUT,
                    checkout=checkout,
                )
                if checkout is not None
                else ContainerlabSourceHint(
                    ContainerlabSourceKind.BINARY,
                    binary=candidate,
                )
            )

    configured_checkout = environ.get("CONTAINERLAB_DIR", "").strip()
    if configured_checkout:
        candidate = Path(configured_checkout).expanduser().resolve()
        if valid_containerlab_checkout(candidate):
            return ContainerlabSourceHint(
                ContainerlabSourceKind.CHECKOUT,
                checkout=candidate,
            )

    if path_binary := shutil.which("containerlab"):
        binary = Path(path_binary).resolve()
        checkout = source_checkout_for_binary(binary)
        return (
            ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=checkout)
            if checkout is not None
            else ContainerlabSourceHint(ContainerlabSourceKind.BINARY, binary=binary)
        )

    managed = state.path("containerlab")
    if valid_containerlab_checkout(managed):
        return ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=managed)

    repository = environ.get("CONTAINERLAB_REPO", DEFAULT_CONTAINERLAB_REPO)
    repository, embedded_revision = _split_repository_revision(repository)
    revision = environ.get("CONTAINERLAB_VERSION", "").strip() or embedded_revision or "HEAD"
    return ContainerlabSourceHint(
        ContainerlabSourceKind.REPOSITORY,
        repository=repository,
        revision=revision,
    )


def resolved_containerlab_source(binary: Path) -> ContainerlabSourceHint:
    checkout = source_checkout_for_binary(binary)
    if checkout is not None:
        return ContainerlabSourceHint(
            ContainerlabSourceKind.CHECKOUT,
            checkout=checkout,
            resolved=True,
        )
    return ContainerlabSourceHint(
        ContainerlabSourceKind.BINARY,
        binary=binary.resolve(),
        resolved=True,
    )


def _split_repository_revision(repository: str) -> tuple[str, str | None]:
    marker = "/tree/"
    if marker in repository and repository.startswith("https://github.com/"):
        base, revision = repository.split(marker, 1)
        if revision:
            return base, revision
    return repository, None


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
