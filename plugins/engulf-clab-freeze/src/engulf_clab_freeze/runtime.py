"""The eclab implementation of the format 3 runtime-provider contract."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from engulf_clab_freeze_api import runtime_provider

from . import command

_DEFAULT_CONTAINERLAB_REPOSITORY = "https://github.com/KarelChanivecky/containerlab"
_DEFAULT_VRNETLAB_REPOSITORY = "https://github.com/KarelChanivecky/vrnetlab"


def _safe_repository(value: str) -> str | None:
    """Keep fetchable public HTTPS locations, never embedded credentials or paths."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    path = parsed.path.split("/tree/", 1)[0] if parsed.hostname == "github.com" else parsed.path
    return urlunsplit((parsed.scheme, parsed.hostname, path, "", ""))


def _git_identity(path: Path) -> dict[str, str] | None:
    if not (path / ".git").exists():
        return None
    try:
        revision = command._run_git(path, "rev-parse", "HEAD")
        remote = command._run_git(path, "remote", "get-url", "origin")
    except (OSError, command.FreezeError):
        return None
    result = {"revision": revision}
    if safe := _safe_repository(remote):
        result["repository"] = safe
    return result


def _containerlab_version(binary: Path) -> dict[str, str] | None:
    try:
        result = subprocess.run([str(binary), "version", "-j"], capture_output=True, text=True, check=False)
        data = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version") or data.get("Version")
    commit = data.get("gitCommit") or data.get("git_commit") or data.get("commit")
    return {key: value for key, value in (("version", version), ("commit", commit)) if isinstance(value, str) and value}


def _containerlab_repository(binary: Path) -> str | None:
    try:
        result = subprocess.run([str(binary), "version", "-j"], capture_output=True, text=True, check=False)
        data = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("repository"), str):
        return _safe_repository(data["repository"])
    return None


def _tool_paths(environment: Mapping[str, str], user_state: Path | None) -> tuple[Path | None, Path | None]:
    binary: Path | None = None
    candidates: list[Path] = []
    if configured := environment.get("CONTAINERLAB_BIN", "").strip():
        candidates.append(Path(configured).expanduser())
    if configured := environment.get("CONTAINERLAB_DIR", "").strip():
        containerlab_dir = Path(configured).expanduser()
        candidates.extend((containerlab_dir / "bin" / "containerlab", containerlab_dir / "containerlab"))
    if found := shutil.which("containerlab", path=environment.get("PATH", os.environ.get("PATH"))):
        candidates.append(Path(found))
    if user_state is not None:
        candidates.extend((user_state / "containerlab" / "bin" / "containerlab", user_state / "containerlab" / "containerlab"))
    for candidate in candidates:
        if command._executable(candidate):
            binary = candidate.resolve()
            break
    checkout: Path | None = None
    configured = environment.get("VRNETLAB_DIR", "")
    candidates = ([Path(configured).expanduser()] if configured else []) + ([user_state / "vrnetlab"] if user_state else [])
    for candidate in candidates:
        if (candidate / "common" / "vrnetlab.py").is_file():
            checkout = candidate.resolve()
            break
    return binary, checkout


def _package_mismatches(root: Path) -> list[str]:
    from importlib import metadata

    path = root / "packages.freeze.txt"
    if not path.is_file():
        return ["installed package manifest is missing"]
    issues: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if match is None:
            issues.append("installed package manifest contains an invalid entry")
            continue
        try:
            actual = metadata.version(match.group(1))
        except metadata.PackageNotFoundError:
            issues.append(f"package {match.group(1)} is missing (frozen {match.group(2)})")
            continue
        if actual != match.group(2):
            issues.append(f"package {match.group(1)} is {actual} (frozen {match.group(2)})")
    return issues


class EclabRuntimeProvider:
    edition = "eclab"

    def capture(self, environment: Mapping[str, str], user_state: Path | None) -> Mapping[str, Any]:
        binary, checkout = _tool_paths(environment, user_state)
        containerlab: dict[str, Any] = {}
        if binary is not None:
            containerlab.update(_containerlab_version(binary) or {})
            for parent in binary.parents:
                if (parent / ".git").exists() and (parent / "go.mod").is_file():
                    containerlab.update(_git_identity(parent) or {})
                    break
            if "repository" not in containerlab:
                configured = environment.get("CONTAINERLAB_REPO", "")
                containerlab["repository"] = _safe_repository(configured) or _containerlab_repository(binary) or _DEFAULT_CONTAINERLAB_REPOSITORY
        vrnetlab = _git_identity(checkout) if checkout is not None else None
        if vrnetlab is not None and "repository" not in vrnetlab:
            vrnetlab["repository"] = _safe_repository(environment.get("VRNETLAB_REPO", "")) or _DEFAULT_VRNETLAB_REPOSITORY
        return {"containerlab": containerlab or None, "vrnetlab": vrnetlab}

    def prepare_archive(self, root: Path, mode: str, tools: Mapping[str, Any], environment: Mapping[str, str], user_state: Path | None, warnings: list[str]) -> None:
        if mode == "lean":
            return
        clab = tools.get("containerlab")
        vrnetlab = tools.get("vrnetlab")
        if not isinstance(clab, dict) or not clab.get("version") or not clab.get("commit"):
            raise command.FreezeError("runtime modes require a verifiable Containerlab version and commit")
        if mode == "offline" and (not isinstance(vrnetlab, dict) or not vrnetlab.get("revision")):
            raise command.FreezeError("--offline requires a verifiable vrnetlab Git revision")
        packages = command._locked_packages()
        (root / "requirements.freeze.txt").write_text("\n".join(f"{name}=={version}" for name, version in packages) + "\n", encoding="utf-8")
        complete = command._download_wheels(root, packages, warnings)
        if mode == "offline" and not complete:
            raise command.FreezeError("--offline requires a complete wheelhouse")
        if mode == "offline":
            assert isinstance(vrnetlab, dict)
            binary, checkout = _tool_paths(environment, user_state)
            if binary is None or checkout is None:
                raise command.FreezeError("--offline requires selected Containerlab and vrnetlab tools")
            if _containerlab_version(binary) != {"version": clab["version"], "commit": clab["commit"]}:
                raise command.FreezeError("Containerlab changed while preparing the offline archive")
            if (_git_identity(checkout) or {}).get("revision") != vrnetlab["revision"]:
                raise command.FreezeError("vrnetlab changed while preparing the offline archive")
            selected = dict(environment)
            selected["CONTAINERLAB_BIN"] = str(binary)
            selected["VRNETLAB_DIR"] = str(checkout)
            command._bundle_offline_runtime(root, self.edition)
            state = _PathState(user_state) if user_state is not None else None
            command._bundle_offline_containerlab(root, state, selected)  # type: ignore[arg-type]
            command._bundle_offline_vrnetlab(root, state, selected)  # type: ignore[arg-type]

    def check_recipient(self, tools: Mapping[str, Any], environment: Mapping[str, str], user_state: Path | None) -> list[str]:
        binary, checkout = _tool_paths(environment, user_state)
        issues: list[str] = []
        recorded_clab = tools.get("containerlab")
        if isinstance(recorded_clab, dict):
            actual = _containerlab_version(binary) if binary is not None else None
            for key in ("version", "commit"):
                expected = recorded_clab.get(key)
                if not expected:
                    issues.append(f"frozen Containerlab {key} is unavailable")
                elif (actual or {}).get(key) != expected:
                    issues.append(f"Containerlab {key} is {(actual or {}).get(key) or 'missing'} (frozen {expected})")
        else:
            issues.append("frozen Containerlab version and commit are unavailable")
        recorded_vrnetlab = tools.get("vrnetlab")
        if isinstance(recorded_vrnetlab, dict) and recorded_vrnetlab.get("revision"):
            actual = _git_identity(checkout) if checkout is not None else None
            if (actual or {}).get("revision") != recorded_vrnetlab["revision"]:
                issues.append(f"vrnetlab revision is {(actual or {}).get('revision') or 'missing'} (frozen {recorded_vrnetlab['revision']})")
        else:
            issues.append("frozen vrnetlab revision is unavailable")
        return issues

    def prepare_recipient(self, root: Path, mode: str, tools: Mapping[str, Any], environment: Mapping[str, str], user_state: Path | None, notes: list[str]) -> None:
        if mode != "runtime":
            return
        from .defrost import DefrostError

        clab = tools.get("containerlab")
        vrnetlab = tools.get("vrnetlab")
        if not isinstance(clab, dict) or not clab.get("version") or not clab.get("commit"):
            raise DefrostError("runtime archive lacks a verifiable Containerlab version and commit")
        vrnetlab_data = vrnetlab if isinstance(vrnetlab, dict) and vrnetlab.get("revision") else None
        binary, checkout = _tool_paths(environment, user_state)
        expected_clab = {"version": clab["version"], "commit": clab["commit"]}
        if binary is None or _containerlab_version(binary) != expected_clab:
            repository = clab.get("repository")
            if not isinstance(repository, str):
                raise DefrostError("recorded Containerlab differs and no safe repository is available")
            destination = root / ".eclab-runtime" / "containerlab-src"
            _clone_revision(repository, clab.get("revision") or clab["commit"], destination)
            (root / ".eclab-runtime" / "bin").mkdir(parents=True, exist_ok=True)
            build = subprocess.run(["go", "build", "-o", str(root / ".eclab-runtime" / "bin" / "containerlab"), "./cmd/containerlab"], cwd=destination, capture_output=True, text=True, check=False)
            if build.returncode:
                raise DefrostError("could not build the pinned Containerlab revision")
            binary = root / ".eclab-runtime" / "bin" / "containerlab"
            if _containerlab_version(binary) != expected_clab:
                raise DefrostError("provisioned Containerlab identity differs from the archive")
        if vrnetlab_data is not None and (checkout is None or (_git_identity(checkout) or {}).get("revision") != vrnetlab_data["revision"]):
            repository = vrnetlab_data.get("repository")
            if not isinstance(repository, str):
                raise DefrostError("recorded vrnetlab differs and no safe repository is available")
            checkout = root / ".eclab-runtime" / "vrnetlab"
            _clone_revision(repository, vrnetlab_data["revision"], checkout)
        lines = []
        if binary is not None:
            lines.append(f"export CONTAINERLAB_BIN={command._shell_quote(str(binary))}")
        if vrnetlab_data is not None and checkout is not None:
            lines.append(f"export VRNETLAB_DIR={command._shell_quote(str(checkout))}")
        lines.extend((
            f"export CONTAINERLAB_VERSION={command._shell_quote(str(clab.get('revision') or clab['commit']))}",
            "export CONTAINERLAB_UPDATE=0",
            "export VRNETLAB_UPDATE=0",
        ))
        if vrnetlab_data is not None:
            lines.append(f"export VRNETLAB_VERSION={command._shell_quote(str(vrnetlab_data['revision']))}")
        (root / ".eclab-freeze.env").write_text("\n".join(lines) + "\n", encoding="utf-8")
        notes.append("pinned Containerlab and vrnetlab are ready")

    def launcher(self, topology: str, mode: str, tools: Mapping[str, Any]) -> str:
        return command._launcher(topology, offline=mode == "offline", mode=mode, edition=self.edition)


def _clone_revision(repository: str, revision: str, destination: Path) -> None:
    from .defrost import DefrostError

    if _safe_repository(repository) != repository or not re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
        raise DefrostError("recorded tool repository or revision is unsafe")
    destination.parent.mkdir(parents=True, exist_ok=True)
    cloned = subprocess.run(["git", "clone", "--", repository, str(destination)], capture_output=True, text=True, check=False)
    if cloned.returncode:
        raise DefrostError("could not clone a pinned tool repository")
    checked = subprocess.run(["git", "-C", str(destination), "checkout", "--detach", revision], capture_output=True, text=True, check=False)
    if checked.returncode or not command._run_git(destination, "rev-parse", "HEAD").startswith(revision):
        raise DefrostError("could not select the pinned tool revision")


class _PathState:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, name: str) -> Path:
        return self.root / name


def _cli() -> int:
    """Prepare deferred pins and verify selected tools before runtime launch."""
    if len(sys.argv) != 3 or sys.argv[1] not in {"prepare", "verify"}:
        print("usage: python -m engulf_clab_freeze.runtime {prepare|verify} LAB", file=sys.stderr)
        return 2
    root = Path(sys.argv[2]).resolve()
    try:
        records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob(".*-defrost.json"))]
        matching = [
            data for data in records
            if isinstance(data, dict)
            and isinstance(data.get("freeze"), dict)
            and data["freeze"].get("format") == 3
            and data["freeze"].get("mode") == "runtime"
        ]
        if len(matching) != 1:
            raise ValueError("expected one format 3 runtime record")
        recorded = matching[0]["freeze"]
        edition = recorded.get("producer_edition")
        if not isinstance(edition, str) or not edition:
            raise ValueError("runtime record has no producer edition")
        tools = recorded.get("tools")
        if not isinstance(tools, dict):
            raise TypeError("runtime record has invalid tool identities")
        provider = runtime_provider(edition)
        if sys.argv[1] == "prepare":
            provider.prepare_recipient(root, "runtime", tools, os.environ, None, [])
        else:
            issues = [issue for issue in provider.check_recipient(tools, os.environ, None) if not issue.startswith("frozen ")]
            if issues:
                raise ValueError("; ".join(issues))
    except (OSError, ValueError, TypeError, StopIteration, KeyError, RuntimeError) as error:
        print(f"pinned runtime check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
