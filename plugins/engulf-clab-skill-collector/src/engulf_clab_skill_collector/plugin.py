from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    InvocationAPI,
    StateScope,
    StateStore,
)
from engulf_clab_schema_api import (
    SCHEMA_REGISTRY_CONTEXT,
    LifecycleStage,
    PathBase,
    PluginSchema,
    SchemaAudience,
    SchemaBackedPlugin,
    ValueType,
    record_plugin_schema,
)
from engulf_clab_skill_api import (
    SKILL_PATHS_CONTEXT,
    SKILL_TEMPORARY_PATHS_CONTEXT,
    SKILL_TRACKED_TARGETS_CONTEXT,
    publish_tracked_skill_targets,
    skill_paths,
    temporary_skill_paths,
    tracked_skill_targets,
)
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    CallMode,
    HelpAPI,
)

PLUGIN_ID = "engulf_clab.skill_collector"
INSTALL_COMMAND = "install-skills"
LEGACY_INSTALL_COMMAND = "install-develop-eclab-lab-skill"
_INSTALL_COMMANDS = frozenset({INSTALL_COMMAND, LEGACY_INSTALL_COMMAND})
INSTALL_REQUEST_CONTEXT = "engulf_clab.skill_collector.install_request"
TARGETS_NAME = "targets.json"
MARKER_NAME = ".engulf-clab-generated.json"
LEGACY_LAB_PLUGIN_ID = "engulf_clab.develop_lab_skill"
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

PLUGIN_SCHEMA = (
    PluginSchema(
        PLUGIN_ID,
        package="engulf_clab_skill_collector",
        audience=SchemaAudience.SUPPORT,
    )
    .add_command(INSTALL_COMMAND, "Install or refresh skills contributed by active plugins.")
    .add_cli_argument(
        INSTALL_COMMAND,
        "CONFIG_ROOT",
        "Select the existing configuration root that contains or will contain skills/.",
        values=ValueType.DIRECTORY_PATH,
    )
    .annotate(
        INSTALL_COMMAND,
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.AFTER_GOAL),
        implies=("The wrapper call is preempted after all contributed skills are installed.",),
        examples=("eclab install-skills ~/.codex",),
    )
    .annotate(
        "CONFIG_ROOT",
        commands=(INSTALL_COMMAND,),
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        path_base=PathBase.INVOCATION_DIRECTORY,
        requires=("The directory exists and is not a symbolic link.",),
        implies=("All active skill directories are installed below CONFIG_ROOT/skills.",),
    )
    .use_case("Install skills contributed by the active plugin set into a coding-agent config root.")
    .reject("Do not point the installer at a skills directory or an unrelated existing skill.")
    .refer("USAGE.md", title="Skill installation guide")
)


@dataclass(frozen=True, slots=True)
class InstallRequest:
    config_root: Path


class SkillCollectorPlugin(SchemaBackedPlugin):
    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = 900
    context_reads = frozenset(
        {
            SCHEMA_REGISTRY_CONTEXT,
            SKILL_PATHS_CONTEXT,
            SKILL_TRACKED_TARGETS_CONTEXT,
            SKILL_TEMPORARY_PATHS_CONTEXT,
            INSTALL_REQUEST_CONTEXT,
        }
    )
    context_writes = frozenset(
        {SCHEMA_REGISTRY_CONTEXT, SKILL_TRACKED_TARGETS_CONTEXT, INSTALL_REQUEST_CONTEXT}
    )

    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        if (
            invocation.arguments
            and invocation.arguments[0] in _INSTALL_COMMANDS
            and ("--help" in invocation.arguments or "-h" in invocation.arguments)
        ):
            return None
        skip_tracking = _skip_tracking(invocation.arguments, invocation.environment)
        if not skip_tracking:
            tracked = self._tracked_targets(api.state(StateScope.USER))
            publish_tracked_skill_targets(api, tracked)
        if not invocation.arguments or invocation.arguments[0] not in _INSTALL_COMMANDS:
            return None
        if len(invocation.arguments) != 2:
            api.logger.error("usage: %s CONFIG_ROOT", INSTALL_COMMAND)
            return GoalResult.rejected(2, rejected_by=self.plugin_id)
        selected = Path(invocation.arguments[1]).expanduser()
        if not selected.is_absolute():
            selected = invocation.cwd / selected
        if selected.is_symlink() or not selected.is_dir():
            api.logger.error("CONFIG_ROOT must be an existing non-symlink directory: %s", selected)
            return GoalResult.rejected(2, rejected_by=self.plugin_id)
        api.set_context(INSTALL_REQUEST_CONTEXT, InstallRequest(selected.resolve()))
        return None

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        del api
        if (
            event.mode is not CallMode.HELP
            and event.wrapper_args
            and event.wrapper_args[0] in _INSTALL_COMMANDS
            and "--help" not in event.wrapper_args
            and "-h" not in event.wrapper_args
        ):
            return CallContribution(preempt_exit_code=0)
        return None

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        temporary_paths = temporary_skill_paths(api)
        try:
            return self._after_goal(invocation, result, api)
        finally:
            _cleanup_temporary_paths(temporary_paths, api)

    def _after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        request_value = api.get_context(INSTALL_REQUEST_CONTEXT)
        request = request_value if isinstance(request_value, InstallRequest) else None
        if request is None and _skip_tracking(invocation.arguments, invocation.environment):
            return result
        paths = skill_paths(api)
        targets = tracked_skill_targets(api)
        state = api.state(StateScope.USER)
        if request is None and not paths and not targets and not _targets(state):
            return result
        if request is not None:
            if result.exit_code != 0:
                return result
            try:
                with api.lease("skill-collector-install"):
                    installed = self._install_paths(api, request.config_root, paths)
                    self._track_root(state, request.config_root, installed)
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                api.logger.error("failed to install contributed skills: %s", error)
                return GoalResult.failed(1, error=str(error))
            api.logger.info("installed %d skill(s) into %s", len(installed), request.config_root)
            return GoalResult.completed(exit_code=0)
        if paths or targets:
            self._refresh(api, state, paths)
        return result

    def help(self, api: HelpAPI) -> str:
        del api
        return f"  {INSTALL_COMMAND} CONFIG_ROOT  Install or refresh skills contributed by active plugins"

    def _tracked_targets(self, state: StateStore) -> tuple[Path, ...]:
        targets: set[Path] = set()
        for record in _targets(state):
            root = Path(record["config_root"])
            for name in record["skills"]:
                target = root / "skills" / name
                marker = _read_marker(target, name)
                if marker is not None:
                    targets.add(target.resolve())
        return tuple(sorted(targets))

    def _install_paths(
        self,
        api: InvocationAPI,
        config_root: Path,
        paths: tuple[Path, ...],
    ) -> tuple[str, ...]:
        names = _validate_sources(paths)
        skills = _prepare_skills_directory(config_root)
        _preflight_targets(skills, paths, names)
        installed: list[str] = []
        for path, name in zip(paths, names, strict=True):
            self._install(api, skills, path, name)
            installed.append(name)
        return tuple(installed)

    def _install(self, api: InvocationAPI, skills: Path, source: Path, name: str) -> None:
        target = skills / name
        backups = skills / f".{name}-backups"
        if backups.is_symlink() or (backups.exists() and not backups.is_dir()):
            raise ValueError(f"refusing unsafe backup directory: {backups}")
        marker = _read_marker(target, name)
        source_fingerprint = _tree_fingerprint(source)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or marker is None:
                raise ValueError(f"refusing to replace unrecognized path: {target}")
            if marker.get("fingerprint") == source_fingerprint:
                _prune_existing_backups(backups, name)
                return

        stage = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=skills))
        backup: Path | None = None
        try:
            _copy_skill(source, stage)
            (stage / MARKER_NAME).write_text(
                json.dumps(
                    {
                        "owner": PLUGIN_ID,
                        "skill_name": name,
                        "fingerprint": source_fingerprint,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            if target.is_dir():
                if backups.is_symlink() or (backups.exists() and not backups.is_dir()):
                    raise ValueError(f"refusing unsafe backup directory: {backups}")
                backups.mkdir(exist_ok=True)
                backup = backups / str(time.time_ns())
                target.replace(backup)
            stage.replace(target)
            if backup is not None:
                _prune_backups(backups, backup)
            else:
                _prune_existing_backups(backups, name)
            api.logger.debug("installed skill %s from %s", name, source)
        except BaseException:
            if backup is not None and backup.exists() and not target.exists():
                backup.replace(target)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _refresh(
        self,
        api: AfterGoalAPI,
        state: StateStore,
        paths: tuple[Path, ...],
    ) -> None:
        with api.lease("skill-collector-install"):
            original = _targets(state)
            records = _merge_tracked_targets(original, tracked_skill_targets(api))
            if not records:
                return
            try:
                names = _validate_sources(paths)
            except (OSError, TypeError, ValueError) as error:
                api.logger.warning("automatic skill refresh skipped: %s", error)
                return
            by_name = dict(zip(names, paths, strict=True))
            retained: list[dict[str, Any]] = []
            for record in records:
                root = Path(record["config_root"])
                remaining: list[str] = []
                for name in record["skills"]:
                    target = root / "skills" / name
                    if not target.exists() and not target.is_symlink():
                        api.logger.info("stopped tracking deleted skill %s", target)
                        continue
                    if _read_marker(target, name) is None:
                        api.logger.warning("stopped tracking unrecognized skill %s", target)
                        continue
                    remaining.append(name)
                    source = by_name.get(name)
                    if source is None:
                        continue
                    try:
                        skills = _prepare_skills_directory(root)
                        self._install(api, skills, source, name)
                    except (OSError, RuntimeError, TypeError, ValueError) as error:
                        api.logger.warning(
                            "automatic skill refresh skipped for %s: %s", target, error
                        )
                if remaining:
                    retained.append({"config_root": str(root), "skills": sorted(set(remaining))})
            if retained != original:
                _write_targets(state, retained)

    def _track_root(
        self,
        state: StateStore,
        config_root: Path,
        installed: tuple[str, ...],
    ) -> None:
        with state.transaction() as transaction:
            records = [
                item for item in _targets(transaction) if item["config_root"] != str(config_root)
            ]
            if installed:
                records.append({"config_root": str(config_root), "skills": sorted(installed)})
            records.sort(key=lambda item: item["config_root"])
            transaction.write_text(
                TARGETS_NAME,
                json.dumps(records, sort_keys=True, indent=2) + "\n",
            )


def _validate_sources(paths: tuple[Path, ...]) -> tuple[str, ...]:
    if type(paths) is not tuple:
        raise TypeError("skill paths must be a tuple")
    names: list[str] = []
    for source in paths:
        if not isinstance(source, Path) or not source.is_absolute():
            raise TypeError("skill source paths must be absolute pathlib.Path values")
        if source.resolve(strict=True) != source:
            raise ValueError(f"skill source path must not traverse symlinks or aliases: {source}")
        name = source.name
        if not _SKILL_NAME.fullmatch(name):
            raise ValueError(f"invalid skill directory name: {name!r}")
        if source.is_symlink() or not source.is_dir():
            raise ValueError(f"skill source is not a safe directory: {source}")
        entrypoint = source / "SKILL.md"
        if entrypoint.is_symlink() or not entrypoint.is_file():
            raise ValueError(f"skill source has no regular SKILL.md: {source}")
        if any(item.is_symlink() for item in source.rglob("*")):
            raise ValueError(f"skill source contains a symbolic link: {source}")
        names.append(name)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate skill directory name(s): {', '.join(duplicates)}")
    return tuple(names)


def _tree_fingerprint(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise ValueError(f"skill source contains an unsupported entry: {path}")
        relative = path.relative_to(source).as_posix().encode("utf-8")
        digest.update(b"D" if path.is_dir() else b"F")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if path.is_file():
            digest.update(path.stat().st_size.to_bytes(8, "big"))
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
    return digest.hexdigest()


def _copy_skill(source: Path, destination: Path) -> None:
    for path in source.iterdir():
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        elif path.is_file() and not path.is_symlink():
            shutil.copy2(path, target)
        else:
            raise ValueError(f"unsupported skill source entry: {path}")


def _prepare_skills_directory(config_root: Path) -> Path:
    if config_root.is_symlink() or not config_root.is_dir():
        raise ValueError(f"unsafe configuration root: {config_root}")
    skills = config_root / "skills"
    if skills.is_symlink():
        raise ValueError(f"refusing symlinked skills directory: {skills}")
    if skills.exists() and not skills.is_dir():
        raise ValueError(f"skills path is not a directory: {skills}")
    skills.mkdir(exist_ok=True)
    return skills


def _preflight_targets(skills: Path, paths: tuple[Path, ...], names: tuple[str, ...]) -> None:
    for name in names:
        target = skills / name
        if (target.exists() or target.is_symlink()) and (
            target.is_symlink() or _read_marker(target, name) is None
        ):
            raise ValueError(f"refusing to replace unrecognized path: {target}")
        backups = skills / f".{name}-backups"
        if backups.is_symlink() or (backups.exists() and not backups.is_dir()):
            raise ValueError(f"refusing unsafe backup directory: {backups}")
    for path in paths:
        _tree_fingerprint(path)


def _read_marker(target: Path, name: str) -> dict[str, object] | None:
    if not target.is_dir() or target.is_symlink():
        return None
    marker_path = target / MARKER_NAME
    if marker_path.is_symlink() or not marker_path.is_file():
        return None
    try:
        value = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("skill_name") != name:
        return None
    owner = value.get("owner")
    legacy = name == "develop-eclab-lab" and owner == LEGACY_LAB_PLUGIN_ID
    if owner != PLUGIN_ID and not legacy:
        return None
    fingerprint = value.get("fingerprint")
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        return None
    entrypoint = target / "SKILL.md"
    if entrypoint.is_symlink() or not entrypoint.is_file():
        return None
    return cast(dict[str, object], value)


def _targets(state: StateStore) -> list[dict[str, Any]]:
    if not state.exists(TARGETS_NAME):
        return []
    try:
        value = json.loads(state.read_text(TARGETS_NAME))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    records: list[dict[str, Any]] = []
    for item in value:
        if (
            isinstance(item, dict)
            and isinstance(item.get("config_root"), str)
            and isinstance(item.get("skills"), list)
            and all(isinstance(name, str) and _SKILL_NAME.fullmatch(name) for name in item["skills"])
        ):
            records.append(
                {"config_root": item["config_root"], "skills": sorted(set(item["skills"]))}
            )
        elif (
            isinstance(item, dict)
            and isinstance(item.get("config_root"), str)
            and item.get("skill_name") == "develop-eclab-lab"
        ):
            # Migrate the former generated-skill target record format.
            records.append(
                {"config_root": item["config_root"], "skills": ["develop-eclab-lab"]}
            )
    by_root: dict[str, set[str]] = {}
    for record in records:
        by_root.setdefault(record["config_root"], set()).update(record["skills"])
    return [
        {"config_root": root, "skills": sorted(names)}
        for root, names in sorted(by_root.items())
    ]


def _merge_tracked_targets(
    records: list[dict[str, Any]],
    targets: tuple[Path, ...],
) -> list[dict[str, Any]]:
    by_root: dict[str, set[str]] = {
        item["config_root"]: set(item["skills"]) for item in records
    }
    for target in targets:
        name = target.name
        if not _SKILL_NAME.fullmatch(name) or _read_marker(target, name) is None:
            continue
        config_root = str(target.parent.parent)
        by_root.setdefault(config_root, set()).add(name)
    return [
        {"config_root": root, "skills": sorted(names)}
        for root, names in sorted(by_root.items())
    ]


def _write_targets(state: StateStore, records: list[dict[str, Any]]) -> None:
    with state.transaction() as transaction:
        transaction.write_text(TARGETS_NAME, json.dumps(records, sort_keys=True, indent=2) + "\n")


def _prune_existing_backups(backups: Path, name: str) -> None:
    if not backups.exists():
        return
    recognized = [
        entry
        for entry in backups.iterdir()
        if entry.is_dir() and not entry.is_symlink() and _read_marker(entry, name) is not None
    ]
    keep = max(recognized, key=lambda entry: entry.name) if recognized else None
    _prune_backups(backups, keep)


def _prune_backups(backups: Path, keep: Path | None) -> None:
    for entry in backups.iterdir():
        if keep is not None and entry == keep:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _skip_tracking(arguments: tuple[str, ...], environment: Mapping[str, str]) -> bool:
    return (
        environment.get("ENGULF_INTERNAL_PROTOCOL") == "1"
        or not arguments
        or arguments[0] == "help"
        or "--help" in arguments
        or "-h" in arguments
    )


def _cleanup_temporary_paths(paths: tuple[Path, ...], api: AfterGoalAPI) -> None:
    for source in paths:
        try:
            if source.is_symlink():
                api.logger.warning("left symlinked temporary skill source untouched: %s", source)
                continue
            if not source.exists():
                continue
            if not source.is_dir() or source.resolve(strict=True) != source:
                api.logger.warning("left unsafe temporary skill source untouched: %s", source)
                continue
            shutil.rmtree(source)
            try:
                source.parent.rmdir()
            except OSError:
                pass
        except (OSError, RuntimeError) as error:
            api.logger.warning("could not remove temporary skill source %s: %s", source, error)


plugin = SkillCollectorPlugin()
