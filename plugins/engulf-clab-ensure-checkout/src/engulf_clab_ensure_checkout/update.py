"""Daily, Git-aware source checkout updates shared by ensure plugins."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from engulf_api import StateStore

from .checkout import CheckoutError, Reporter

_CHECKS_FILE = "update-checks.json"
_DAY_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class UpdateConfig:
    """Environment names and labels for one updateable checkout."""

    label: str
    update_env: str
    version_env: str


def update_requested(environ: Mapping[str, str], config: UpdateConfig) -> bool:
    """Return whether an update or explicit revision clamp was requested."""
    version = environ.get(config.version_env, "").strip()
    value = environ.get(config.update_env, "").strip().lower()
    return bool(version) or value not in {"", "0", "false", "no", "off"}


def update_checkout(
    state: StateStore,
    checkout: Path,
    environ: Mapping[str, str],
    *,
    config: UpdateConfig,
    info: Reporter,
    now: float | None = None,
) -> bool:
    """Update a clean Git checkout at most once per day.

    Version values are Git tags, commits, or references. Without a clamp, the
    latest tag reachable from the checkout branch wins; branches without tags
    fast-forward from commits. Non-Git directories are deliberately untouched.
    """
    if not update_requested(environ, config) or not _is_git_checkout(checkout):
        return False

    timestamp = time.time() if now is None else now
    key = hashlib.sha256(str(checkout.resolve()).encode()).hexdigest()
    version = environ.get(config.version_env, "").strip()
    with state.transaction():
        checks = _read_checks(state)
        record = checks.get(key, {})
        previous = record.get("checked_at")
        if (
            isinstance(previous, (int, float))
            and timestamp - previous < _DAY_SECONDS
            and record.get("requested_version") == version
        ):
            return False

        if _git(checkout, "status", "--porcelain").strip():
            raise CheckoutError(f"cannot update {config.label}: checkout has local changes")

        before = _git(checkout, "rev-parse", "HEAD").strip()
        branch = _current_branch(checkout) or record.get("branch") or _default_branch(checkout)
        has_origin = _has_origin(checkout)
        if has_origin:
            _git(checkout, "fetch", "--tags", "--prune", "origin")
        if version:
            _git(checkout, "rev-parse", "--verify", f"{version}^{{commit}}")
            _git(checkout, "checkout", "--detach", version)
            info(f"clamped {config.label} to {version}")
        elif isinstance(branch, str) and branch:
            tag = _latest_release_tag(checkout, branch, has_origin=has_origin)
            if tag:
                _git(checkout, "checkout", "--detach", tag)
                info(f"updated {config.label} to release tag {tag}")
            elif has_origin:
                _git(checkout, "checkout", branch)
                _git(checkout, "merge", "--ff-only", f"origin/{branch}")
                info(f"updated {config.label} from branch {branch}")
            else:
                info(f"not updating {config.label}: checkout has no origin remote")
        else:
            raise CheckoutError(f"cannot update {config.label}: no branch could be determined")

        new_record: dict[str, object] = {
            "checked_at": timestamp,
            "requested_version": version,
        }
        if isinstance(branch, str) and branch:
            new_record["branch"] = branch
        checks[key] = new_record
        _write_checks(state, checks)
        return _git(checkout, "rev-parse", "HEAD").strip() != before


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *args], check=False, text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CheckoutError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _is_git_checkout(checkout: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--is-inside-work-tree"],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _current_branch(checkout: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(checkout), "symbolic-ref", "--quiet", "--short", "HEAD"],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def _default_branch(checkout: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(checkout), "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        return None
    remote = result.stdout.strip()
    return remote.removeprefix("origin/") or None


def _has_origin(checkout: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(checkout), "remote", "get-url", "origin"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _latest_release_tag(checkout: Path, branch: str, *, has_origin: bool) -> str | None:
    tags = _git(
        checkout, "tag", "--merged", f"origin/{branch}" if has_origin else branch,
        "--sort=-v:refname",
    ).splitlines()
    return next((tag for tag in tags if _RELEASE_TAG.fullmatch(tag)), None)


_RELEASE_TAG = re.compile(r"v?\d+(?:\.\d+)+")


def _read_checks(state: StateStore) -> dict[str, dict[str, object]]:
    if not state.exists(_CHECKS_FILE):
        return {}
    try:
        parsed = json.loads(state.read_text(_CHECKS_FILE))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {key: value for key, value in parsed.items() if isinstance(key, str) and isinstance(value, dict)}


def _write_checks(state: StateStore, checks: Mapping[str, Mapping[str, object]]) -> None:
    state.write_text(_CHECKS_FILE, json.dumps(checks, sort_keys=True))
