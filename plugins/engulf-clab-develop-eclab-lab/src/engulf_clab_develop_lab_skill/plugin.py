from __future__ import annotations

import hashlib
import importlib.resources
import json
import shutil
import tempfile
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from engulf_api import (
    AfterGoalAPI,
    ApplicationMetadata,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    RegistrationAPI,
    StateScope,
    StateStore,
)
from engulf_clab_schema import bundle_directory_complete
from engulf_clab_schema_api import (
    ECLAB_SCHEMA_PIPELINE_ID,
    SCHEMA_COMPILED_CONTEXT,
    SCHEMA_REGISTRY_CONTEXT,
    SCHEMA_REQUEST_CONTEXT,
    CompiledSchemaBundle,
    LifecycleStage,
    PathBase,
    PluginSchema,
    SchemaBackedPlugin,
    SchemaBuildRequest,
    ValueType,
    compiled_schema,
    normalized_short_product,
    record_plugin_schema,
    request_schema_build,
)
from engulf_executable_wrapper_api import ArgumentRegistry, CompletionRegistry, HelpAPI

PLUGIN_ID = "engulf_clab.develop_lab_skill"
INSTALL_REQUEST_CONTEXT = "engulf_clab.develop_lab_skill.install_request"
MARKER_NAME = ".engulf-clab-generated.json"
TARGETS_NAME = "targets.json"
ECLAB_SHORT_PRODUCT = ECLAB_SCHEMA_PIPELINE_ID
ECLAB_INSTALL_COMMAND = "install-develop-eclab-lab-skill"
ECLAB_SKILL_NAME = "develop-eclab-lab"

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_develop_lab_skill")
    .add_command(
        ECLAB_INSTALL_COMMAND,
        "Install or refresh the runtime-aware lab development skill.",
    )
    .add_cli_argument(
        ECLAB_INSTALL_COMMAND,
        "CONFIG_ROOT",
        "Select the configuration root that contains the skills directory.",
        values=ValueType.DIRECTORY_PATH,
    )
    .annotate(
        ECLAB_INSTALL_COMMAND,
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.AFTER_GOAL),
        implies=("The wrapper call is preempted after the generated skill is installed.",),
        examples=("eclab install-develop-eclab-lab-skill ~/.codex",),
    )
    .annotate(
        "CONFIG_ROOT",
        commands=(ECLAB_INSTALL_COMMAND,),
        lifecycle=(LifecycleStage.BEFORE_GOAL,),
        path_base=PathBase.INVOCATION_DIRECTORY,
        requires=("The directory exists and is not a symbolic link.",),
        implies=("The skill is installed below CONFIG_ROOT/skills.",),
    )
    .use_case("Install an exact active-plugin schema for a coding agent before lab authoring.")
    .reject("Do not point the installer at a skills directory or an existing unrelated skill.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "The installer requests a build before the schema generator compiles the recorded registry.",
        before=("engulf_clab.schema",),
    )
    .route(
        "install-generated-skill",
        "USAGE.md",
        "Read destination safety, atomic replacement, backups, and refresh triggers.",
    )
    .refer("USAGE.md", title="Generated skill installation guide")
)


@dataclass(frozen=True, slots=True)
class SkillInstallRequest:
    config_root: Path
    skill_name: str
    command: str
    request_id: str


class DevelopLabSkillPlugin(SchemaBackedPlugin):
    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = -900
    context_reads = frozenset(
        {
            SCHEMA_REGISTRY_CONTEXT,
            SCHEMA_REQUEST_CONTEXT,
            SCHEMA_COMPILED_CONTEXT,
            INSTALL_REQUEST_CONTEXT,
        }
    )
    context_writes = frozenset(
        {SCHEMA_REGISTRY_CONTEXT, SCHEMA_REQUEST_CONTEXT, INSTALL_REQUEST_CONTEXT}
    )

    def register_arguments(
        self,
        registry: ArgumentRegistry,
        api: RegistrationAPI,
    ) -> None:
        if _is_eclab_application(api.application):
            super().register_arguments(registry, api)

    def register_completions(
        self,
        registry: CompletionRegistry,
        api: RegistrationAPI,
    ) -> None:
        if _is_eclab_application(api.application):
            super().register_completions(registry, api)

    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        if not _is_eclab_application(api.application):
            return None
        record_plugin_schema(api, PLUGIN_SCHEMA)
        command = install_command()
        if not invocation.arguments or invocation.arguments[0] != command:
            if _skip_automatic_refresh(invocation.arguments, invocation.environment):
                return None
            tracked, current_fingerprint = self._tracked_fingerprint(api)
            if tracked:
                request_schema_build(
                    api,
                    SchemaBuildRequest(
                        self.plugin_id,
                        uuid.uuid4().hex,
                        required=False,
                        current_fingerprint=current_fingerprint,
                        pipeline_id=ECLAB_SCHEMA_PIPELINE_ID,
                    ),
                )
            return None
        if len(invocation.arguments) != 2:
            api.logger.error("usage: %s CONFIG_ROOT", command)
            return GoalResult.rejected(2, rejected_by=self.plugin_id)
        raw_root = Path(invocation.arguments[1]).expanduser()
        selected_root = raw_root if raw_root.is_absolute() else invocation.cwd / raw_root
        if selected_root.is_symlink():
            api.logger.error("CONFIG_ROOT must not be a symlink: %s", selected_root)
            return GoalResult.rejected(2, rejected_by=self.plugin_id)
        config_root = selected_root.resolve()
        if not config_root.is_dir():
            api.logger.error(
                "CONFIG_ROOT must be an existing non-symlink directory: %s", config_root
            )
            return GoalResult.rejected(2, rejected_by=self.plugin_id)
        request = SkillInstallRequest(
            config_root,
            skill_name(),
            command,
            uuid.uuid4().hex,
        )
        api.set_context(INSTALL_REQUEST_CONTEXT, request)
        request_schema_build(
            api,
            SchemaBuildRequest(
                self.plugin_id,
                request.request_id,
                required=True,
                pipeline_id=ECLAB_SCHEMA_PIPELINE_ID,
            ),
        )
        return None

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        del invocation
        if not _is_eclab_application(api.application):
            return result
        request_value = api.get_context(INSTALL_REQUEST_CONTEXT)
        request = request_value if isinstance(request_value, SkillInstallRequest) else None
        bundle = compiled_schema(api, ECLAB_SCHEMA_PIPELINE_ID)
        if request is not None:
            if bundle is None:
                if result.exit_code == 0:
                    return GoalResult.failed(
                        1, error="schema generator produced no installable bundle"
                    )
                return result
            try:
                target = self._install(api, request.config_root, request.skill_name, bundle)
                _record_target(api.state(StateScope.USER), request.config_root, request.skill_name)
            except (OSError, RuntimeError, ValueError) as error:
                api.logger.error("failed to install generated skill: %s", error)
                return GoalResult.failed(1, error=str(error))
            api.logger.info("installed %s", target)
            return GoalResult.completed(bundle)
        if bundle is not None:
            self._refresh_tracked(api, bundle)
        return result

    def help(self, api: HelpAPI) -> str:
        if not _is_eclab_application(api.application):
            return ""
        command = install_command()
        return f"  {command} CONFIG_ROOT  Install or refresh the runtime-aware development skill"

    def _refresh_tracked(self, api: AfterGoalAPI, bundle: CompiledSchemaBundle) -> None:
        state = api.state(StateScope.USER)
        retained: list[dict[str, str]] = []
        for record in _targets(state):
            root = Path(record["config_root"])
            name = record["skill_name"]
            target = root / "skills" / name
            if not target.exists() and not target.is_symlink():
                api.logger.info("stopped tracking deleted generated skill %s", target)
                continue
            retained.append(record)
            try:
                self._install(api, root, name, bundle)
            except (OSError, RuntimeError, ValueError) as error:
                api.logger.warning("automatic skill refresh skipped for %s: %s", target, error)
        if retained != _targets(state):
            _write_targets(state, retained)

    def _tracked_fingerprint(self, api: BeforeGoalAPI) -> tuple[bool, str | None]:
        state = api.state(StateScope.USER)
        records = _targets(state)
        retained: list[dict[str, str]] = []
        fingerprints: list[str | None] = []
        for record in records:
            target = Path(record["config_root"]) / "skills" / record["skill_name"]
            if not target.exists() and not target.is_symlink():
                api.logger.info("stopped tracking deleted generated skill %s", target)
                continue
            if _marker(target) is None:
                api.logger.warning("stopped tracking unrecognized generated skill %s", target)
                continue
            retained.append(record)
            fingerprint = _installed_fingerprint(target)
            if fingerprint is None:
                api.logger.info(
                    "generated skill runtime is missing or incomplete; requesting refresh for %s",
                    target,
                )
            fingerprints.append(fingerprint)
        if retained != records:
            _write_targets(state, retained)
        current = (
            fingerprints[0]
            if fingerprints
            and fingerprints[0] is not None
            and all(item == fingerprints[0] for item in fingerprints)
            else None
        )
        return bool(retained), current

    def _install(
        self,
        api: AfterGoalAPI,
        config_root: Path,
        name: str,
        bundle: CompiledSchemaBundle,
    ) -> Path:
        if name != ECLAB_SKILL_NAME:
            raise ValueError(f"unsupported generated skill target: {name}")
        if bundle.pipeline_id != ECLAB_SCHEMA_PIPELINE_ID:
            raise ValueError(
                f"cannot install {bundle.pipeline_id} schema as the eclab development skill"
            )
        skills = config_root / "skills"
        if config_root.is_symlink() or not config_root.is_dir():
            raise ValueError(f"unsafe configuration root: {config_root}")
        if skills.is_symlink():
            raise ValueError(f"refusing symlinked skills directory: {skills}")
        skills.mkdir(parents=True, exist_ok=True)
        target = skills / name
        backups = skills / f".{name}-backups"
        lease = hashlib.sha256(str(target).encode()).hexdigest()
        with api.lease(f"generated-skill:{lease}"):
            marker = _marker(target)
            if target.exists() or target.is_symlink():
                if target.is_symlink() or marker is None:
                    raise ValueError(f"refusing to replace unrecognized path: {target}")
                if _installed_fingerprint(target) == bundle.fingerprint:
                    _prune_runtimes(
                        target / "references" / "runtimes",
                        keep=bundle.fingerprint,
                    )
                    if backups.is_dir() and not backups.is_symlink():
                        _prune_backups(backups)
                    return target
            staged = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=skills))
            carried: Path | None = None
            backup: Path | None = None
            try:
                _write_static_skill(
                    staged,
                    catalog_markdown=bundle.catalog_markdown,
                    fingerprint=bundle.fingerprint,
                )
                if target.is_dir():
                    previous_runtimes = target / "references" / "runtimes"
                    if previous_runtimes.is_dir() and not previous_runtimes.is_symlink():
                        previous_runtimes.rename(staged / "references" / "runtimes")
                        carried = previous_runtimes
                runtime = staged / "references" / "runtimes" / bundle.fingerprint
                runtime.mkdir(parents=True, exist_ok=True)
                (runtime / "manifest.json").write_bytes(bundle.manifest)
                (runtime / "clab.schema.json").write_bytes(bundle.topology_schema)
                (runtime / "catalog.json").write_bytes(bundle.catalog_json)
                (runtime / "catalog.md").write_bytes(bundle.catalog_markdown)
                for plugin_schema in bundle.plugin_schemas:
                    destination = runtime / "plugins" / plugin_schema.plugin_id / plugin_schema.path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(plugin_schema.content)
                for reference in bundle.references:
                    destination = runtime / "plugins" / reference.plugin_id / reference.path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(reference.content)
                current = {
                    "fingerprint": bundle.fingerprint,
                    "pipeline_id": bundle.pipeline_id,
                    "manifest": f"runtimes/{bundle.fingerprint}/manifest.json",
                    "catalog": f"runtimes/{bundle.fingerprint}/catalog.md",
                    "catalog_json": f"runtimes/{bundle.fingerprint}/catalog.json",
                    "topology_schema": f"runtimes/{bundle.fingerprint}/clab.schema.json",
                }
                (staged / "references" / "current.json").write_text(
                    json.dumps(current, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                (staged / MARKER_NAME).write_text(
                    json.dumps(
                        {
                            "owner": PLUGIN_ID,
                            "skill_name": name,
                            "pipeline_id": bundle.pipeline_id,
                            "fingerprint": bundle.fingerprint,
                        },
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                if target.is_dir():
                    backups.mkdir(exist_ok=True)
                    backup = backups / f"{time.time_ns()}"
                    target.replace(backup)
                staged.replace(target)
                _prune_runtimes(
                    target / "references" / "runtimes",
                    keep=bundle.fingerprint,
                )
                if backup is not None:
                    _prune_backups(backups, keep=backup)
            except BaseException:
                if backup is not None and backup.exists() and not target.exists():
                    backup.replace(target)
                staged_runtimes = staged / "references" / "runtimes"
                if (
                    carried is not None
                    and carried.parent.exists()
                    and not carried.exists()
                    and staged_runtimes.is_dir()
                ):
                    staged_runtimes.rename(carried)
                raise
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
        return target


def install_command() -> str:
    return ECLAB_INSTALL_COMMAND


def skill_name() -> str:
    return ECLAB_SKILL_NAME


def _is_runtime_fingerprint(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _prune_runtimes(runtimes: Path, *, keep: str) -> None:
    """Keep the active runtime and leave unrelated entries untouched."""
    if not _is_runtime_fingerprint(keep):
        raise ValueError("cannot retain an invalid runtime fingerprint")
    if not runtimes.is_dir() or runtimes.is_symlink():
        return
    try:
        entries = tuple(runtimes.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name == keep or not _is_runtime_fingerprint(entry.name):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            shutil.rmtree(entry)
        except OSError:
            # Retention is housekeeping; failure must not invalidate a new install.
            continue


def _prune_backups(backups: Path, *, keep: Path | None = None) -> None:
    """Keep only the selected (latest) generated-skill backup."""
    entries = list(backups.iterdir())
    if keep is None:
        candidates = [entry for entry in entries if entry.name.isdigit()]
        keep = max(candidates, key=lambda entry: int(entry.name), default=None)
    for entry in entries:
        if keep is not None and entry == keep:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _is_eclab_application(application: ApplicationMetadata) -> bool:
    return normalized_short_product(application) == ECLAB_SCHEMA_PIPELINE_ID


def _skip_automatic_refresh(
    arguments: tuple[str, ...],
    environment: Mapping[str, str],
) -> bool:
    return (
        environment.get("ENGULF_INTERNAL_PROTOCOL") == "1"
        or not arguments
        or arguments[0] == "help"
        or "--help" in arguments
        or "-h" in arguments
    )


def _write_static_skill(
    destination: Path,
    *,
    catalog_markdown: bytes | None = None,
    fingerprint: str | None = None,
) -> None:
    name = skill_name()
    short_product = ECLAB_SHORT_PRODUCT
    command = install_command()
    source = _skill_source()
    replacements = {
        "@@SKILL_NAME@@": name,
        "@@SHORT_PRODUCT@@": short_product,
        "@@INSTALL_COMMAND@@": command,
    }
    definition = _render(source / "SKILL.md", replacements)
    if catalog_markdown is not None:
        if fingerprint is None:
            raise ValueError("fingerprint is required when embedding a runtime catalog")
        definition = f"{definition.rstrip()}\n\n{_embedded_catalog(catalog_markdown, fingerprint)}"
    agents = _render(source / "agents" / "openai.yaml", replacements)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "SKILL.md").write_text(definition, encoding="utf-8")
    (destination / "agents").mkdir()
    (destination / "agents" / "openai.yaml").write_text(agents, encoding="utf-8")
    (destination / "references").mkdir()


def _embedded_catalog(content: bytes, fingerprint: str) -> str:
    catalog = content.decode("utf-8")
    runtime = f"references/runtimes/{fingerprint}/"
    lines: list[str] = []
    for line in catalog.splitlines():
        if line.startswith("#"):
            line = f"#{line}"
        line = line.replace("`plugins/", f"`{runtime}plugins/")
        line = line.replace("`clab.schema.json`", f"`{runtime}clab.schema.json`")
        lines.append(line)
    return "\n".join(lines) + "\n"


def _skill_source() -> Path:
    resource = importlib.resources.files("engulf_clab_develop_lab_skill").joinpath("skill")
    if resource.is_dir() and isinstance(resource, Path):
        return resource
    package = Path(__file__).resolve().parent
    source = package.parent.parent / "skill"
    if source.is_dir():
        return source
    raise RuntimeError("generated skill package does not contain its skill template")


def _render(path: Path, replacements: dict[str, str]) -> str:
    content = path.read_text(encoding="utf-8")
    for source, target in replacements.items():
        content = content.replace(source, target)
    if "@@" in content:
        raise RuntimeError(f"unresolved skill template marker in {path}")
    return content


def _marker(target: Path) -> dict[str, object] | None:
    if not target.is_dir() or target.is_symlink():
        return None
    path = target / MARKER_NAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("owner") != PLUGIN_ID
        or value.get("skill_name") != ECLAB_SKILL_NAME
        or value.get("pipeline_id", ECLAB_SCHEMA_PIPELINE_ID) != ECLAB_SCHEMA_PIPELINE_ID
    ):
        return None
    return value


def _installed_fingerprint(target: Path) -> str | None:
    marker = _marker(target)
    if marker is None:
        return None
    fingerprint = marker.get("fingerprint")
    if not isinstance(fingerprint, str):
        return None
    if not (target / "SKILL.md").is_file() or (target / "SKILL.md").is_symlink():
        return None
    agent = target / "agents" / "openai.yaml"
    if not agent.is_file() or agent.is_symlink():
        return None
    current_path = target / "references" / "current.json"
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(current, dict)
        or current.get("fingerprint") != fingerprint
        or current.get("pipeline_id", ECLAB_SCHEMA_PIPELINE_ID) != ECLAB_SCHEMA_PIPELINE_ID
    ):
        return None
    runtime = target / "references" / "runtimes" / fingerprint
    return (
        fingerprint
        if bundle_directory_complete(
            runtime,
            fingerprint,
            pipeline_id=ECLAB_SCHEMA_PIPELINE_ID,
        )
        else None
    )


def _targets(state: StateStore) -> list[dict[str, str]]:
    if not state.exists(TARGETS_NAME):
        return []
    try:
        value = json.loads(state.read_text(TARGETS_NAME))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    return [
        {"config_root": item["config_root"], "skill_name": item["skill_name"]}
        for item in value
        if isinstance(item, dict)
        and isinstance(item.get("config_root"), str)
        and isinstance(item.get("skill_name"), str)
        and item["skill_name"] == ECLAB_SKILL_NAME
    ]


def _write_targets(state: StateStore, records: list[dict[str, str]]) -> None:
    with state.transaction() as transaction:
        transaction.write_text(TARGETS_NAME, json.dumps(records, sort_keys=True, indent=2) + "\n")


def _record_target(state: StateStore, config_root: Path, name: str) -> None:
    with state.transaction() as transaction:
        records = _targets(transaction)
        record = {"config_root": str(config_root), "skill_name": name}
        if record not in records:
            records.append(record)
            records.sort(key=lambda item: (item["config_root"], item["skill_name"]))
            transaction.write_text(
                TARGETS_NAME,
                json.dumps(records, sort_keys=True, indent=2) + "\n",
            )


plugin = DevelopLabSkillPlugin()
