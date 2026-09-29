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

import yaml  # type: ignore[import-untyped]
from engulf_clab_freeze_api import runtime_provider

from . import command

_DEFAULT_CONTAINERLAB_REPOSITORY = "https://github.com/KarelChanivecky/containerlab"
_DEFAULT_VRNETLAB_REPOSITORY = "https://github.com/KarelChanivecky/vrnetlab"
# Records the source revision of a bundled vrnetlab tree, which has no .git.
_REVISION_MARKER = ".eclab-freeze-revision"


def _safe_repository(value: str) -> str | None:
    """Keep fetchable public HTTPS locations, never embedded credentials or paths."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    path = parsed.path.split("/tree/", 1)[0] if parsed.hostname == "github.com" else parsed.path
    return urlunsplit((parsed.scheme, parsed.hostname, path, "", ""))


def _git_identity(path: Path) -> dict[str, str] | None:
    pinned = path / _REVISION_MARKER
    if pinned.is_file():
        revision = pinned.read_text(encoding="ascii").strip()
        return {"revision": revision} if re.fullmatch(r"[0-9a-fA-F]{7,40}", revision) else None
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


def _package_mismatches(
    root: Path, runtime_packages: object = None, *, edition: str = "eclab"
) -> list[str]:
    """Compare runtime dependencies while retaining the full producer inventory.

    Older format 3 archives have no runtime package list. For those, compare
    the recipient's active runtime closure and archived Engulf distributions;
    unrelated producer development tools are only provenance.
    """
    from importlib import metadata

    path = root / "packages.freeze.txt"
    if not path.is_file():
        return ["installed package manifest is missing"]
    if runtime_packages is None:
        required = {name for name, _ in command._locked_packages(edition)}
        legacy = True
    elif isinstance(runtime_packages, list) and all(
        isinstance(name, str) and name for name in runtime_packages
    ):
        required = set(runtime_packages)
        legacy = False
    else:
        return ["runtime package inventory is invalid"]
    issues: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if match is None:
            issues.append("installed package manifest contains an invalid entry")
            continue
        name = match.group(1)
        if legacy and (name.startswith("engulf-") or name == "fclab"):
            required.add(name)
        if name not in required:
            continue
        required.discard(name)
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            issues.append(f"package {name} is missing (frozen {match.group(2)})")
            continue
        if actual != match.group(2):
            issues.append(f"package {name} is {actual} (frozen {match.group(2)})")
    if not legacy and required:
        issues.append(
            "runtime package inventory has no frozen version for: "
            + ", ".join(sorted(required))
        )
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
            raise command.FreezeError("--eclab-offline requires a verifiable vrnetlab Git revision")
        packages = command._locked_packages(self.edition)
        (root / "requirements.freeze.txt").write_text("\n".join(f"{name}=={version}" for name, version in packages) + "\n", encoding="utf-8")
        complete = command._download_wheels(root, packages, warnings)
        if mode == "offline" and not complete:
            raise command.FreezeError("--eclab-offline requires a complete wheelhouse")
        if mode == "offline":
            command._bundle_offline_runtime(root, self.edition)
        else:
            # The recipient builds its virtual environment without a
            # package index, so every locked wheel must travel with the lab.
            if not complete:
                raise command.FreezeError("--eclab-with-runtime requires a complete wheelhouse")
            command._download_python_wheels(root, warnings)
        self._bundle_tools(root, mode, clab, vrnetlab, environment, user_state)

    def _bundle_tools(
        self,
        root: Path,
        mode: str,
        clab: Mapping[str, Any],
        vrnetlab: object,
        environment: Mapping[str, str],
        user_state: Path | None,
    ) -> None:
        """Copy the producer's exact tools so the recipient never fetches them.

        The archive carries the selected Containerlab executable and the
        vrnetlab working tree as they are on the producing host, including
        local commits and uncommitted changes, so a recipient runs exactly
        what the lab was frozen with even when that state was never pushed.
        """
        label = "--eclab-offline" if mode == "offline" else "runtime mode"
        if not isinstance(vrnetlab, dict) or not isinstance(vrnetlab.get("revision"), str):
            raise command.FreezeError(f"{label} requires a verifiable vrnetlab Git revision")
        binary, checkout = _tool_paths(environment, user_state)
        if binary is None or checkout is None:
            raise command.FreezeError(f"{label} requires selected Containerlab and vrnetlab tools")
        if _containerlab_version(binary) != {"version": clab["version"], "commit": clab["commit"]}:
            raise command.FreezeError(f"Containerlab changed while preparing the {mode} archive")
        if (_git_identity(checkout) or {}).get("revision") != vrnetlab["revision"]:
            raise command.FreezeError(f"vrnetlab changed while preparing the {mode} archive")
        selected = dict(environment)
        selected["CONTAINERLAB_BIN"] = str(binary)
        selected["VRNETLAB_DIR"] = str(checkout)
        state = _PathState(user_state) if user_state is not None else None
        command._bundle_offline_containerlab(root, state, selected)  # type: ignore[arg-type]
        command._bundle_offline_vrnetlab(root, state, selected)  # type: ignore[arg-type]
        (root / "tools" / "vrnetlab" / _REVISION_MARKER).write_text(
            vrnetlab["revision"] + "\n", encoding="ascii"
        )

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
        # Runtime archives run only the tools frozen beside the lab, installed
        # into the lab's own virtual environment. Never fetch or rebuild them:
        # a producer revision may exist nowhere else, and host tool
        # selections must not leak into the pinned launcher.
        venv = root / ".eclab-venv"
        if not (venv / "bin" / "python").is_file():
            raise DefrostError("runtime virtual environment is missing; run the lab launcher to create it")
        source = root / "tools" / "containerlab" / "bin" / "containerlab"
        if not command._executable(source):
            raise DefrostError(
                "runtime archive has no bundled Containerlab executable; re-freeze it with --eclab-with-runtime"
            )
        expected_clab = {"version": clab["version"], "commit": clab["commit"]}
        if _containerlab_version(source) != expected_clab:
            raise DefrostError("bundled Containerlab identity differs from the archive record")
        binary = venv / "bin" / "containerlab"
        shutil.copy2(source, binary)
        binary.chmod(binary.stat().st_mode | 0o111)
        checkout = None
        if vrnetlab_data is not None:
            bundled = root / "tools" / "vrnetlab"
            if not (bundled / "common" / "vrnetlab.py").is_file():
                raise DefrostError(
                    "runtime archive has no bundled vrnetlab checkout; re-freeze it with --eclab-with-runtime"
                )
            if (_git_identity(bundled) or {}).get("revision") != vrnetlab_data["revision"]:
                raise DefrostError("bundled vrnetlab revision differs from the archive record")
            checkout = venv / "share" / "vrnetlab"
            shutil.rmtree(checkout, ignore_errors=True)
            shutil.copytree(bundled, checkout, symlinks=True)
        lines = []
        lines.append(f"export CONTAINERLAB_BIN={command._shell_quote(str(binary))}")
        lines.append(f"export PATH={command._shell_quote(str(binary.parent))}:\"$PATH\"")
        if checkout is not None:
            lines.append(f"export VRNETLAB_DIR={command._shell_quote(str(checkout))}")
        lines.extend((
            "export CONTAINERLAB_UPDATE=0",
            "export VRNETLAB_UPDATE=0",
        ))
        (root / ".eclab-freeze.env").write_text("\n".join(lines) + "\n", encoding="utf-8")
        notes.append("installed bundled Containerlab and vrnetlab into .eclab-venv")

    def launcher(self, topology: str, mode: str, tools: Mapping[str, Any]) -> str:
        return command._launcher(topology, offline=mode == "offline", mode=mode, edition=self.edition)

    def readme_supplement(self, mode: str) -> str:
        """Edition-specific markdown appended to the archived FREEZE-README.md.

        The base guide (``readmes/{mode}.md``) covers what every edition
        shares; an edition override explains only what its plugins add.
        Rendered with the same substitutions as the base template, so the
        supplement may use ``$edition``/``$topology``/``$launcher``.
        """
        return ""


class _PathState:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, name: str) -> Path:
        return self.root / name


def _runtime_record(root: Path) -> dict[str, Any]:
    """Read the runtime freeze record from defrost, or from the archived topology.

    A recipient may run the launcher straight from an extracted archive, so
    the topology's own freeze metadata is the fallback when defrost never ran.
    """
    records = [json.loads(path.read_text(encoding="utf-8")).get("freeze") for path in sorted(root.glob(".*-defrost.json"))]
    if not records:
        for path in sorted(root.glob("*.y*ml")):
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError):
                continue
            if isinstance(document, dict):
                records.append(document.get(command._FREEZE_KEY))
    matching = [
        data for data in records
        if isinstance(data, dict) and data.get("format") == 3 and data.get("mode") == "runtime"
    ]
    if len(matching) != 1:
        raise ValueError("expected one format 3 runtime record")
    return matching[0]


def _cli() -> int:
    """Prepare deferred pins and verify selected tools before runtime launch."""
    if len(sys.argv) != 3 or sys.argv[1] not in {"prepare", "verify"}:
        print("usage: python -m engulf_clab_freeze.runtime {prepare|verify} LAB", file=sys.stderr)
        return 2
    root = Path(sys.argv[2]).resolve()
    try:
        recorded = _runtime_record(root)
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
