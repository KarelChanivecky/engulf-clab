from __future__ import annotations

import hashlib
import importlib.resources
import json
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from engulf_api import (
    AfterGoalAPI,
    BeforeGoalAPI,
    DependencyPosition,
    GoalResult,
    Invocation,
    PluginDependency,
    StateScope,
    StateStore,
)
from engulf_clab_schema_api import (
    SCHEMA_COMPILED_CONTEXT,
    SCHEMA_PLUGIN_ID,
    SCHEMA_REGISTRY_CONTEXT,
    SCHEMA_REQUEST_CONTEXT,
    CompiledSchemaBundle,
    LifecycleStage,
    PathBase,
    PluginSchema,
    SchemaBuildRequest,
    ValueType,
    normalized_short_product,
    record_plugin_schema,
    request_schema_build,
)
from engulf_executable_wrapper_api import ExecutableWrapperPlugin, HelpAPI

PLUGIN_ID = "engulf_clab.develop_lab_skill"
INSTALL_REQUEST_CONTEXT = "engulf_clab.develop_lab_skill.install_request"
MARKER_NAME = ".engulf-clab-generated.json"
TARGETS_NAME = "targets.json"

PLUGIN_SCHEMA = (
    PluginSchema(PLUGIN_ID, package="engulf_clab_develop_lab_skill")
    .add_command(
        "install-develop-{short_product}-lab-skill",
        "Install or refresh the runtime-aware lab development skill.",
    )
    .add_cli_argument(
        "install-develop-{short_product}-lab-skill",
        "CONFIG_ROOT",
        "Select the configuration root that contains the skills directory.",
        values=ValueType.DIRECTORY_PATH,
    )
    .annotate(
        "install-develop-{short_product}-lab-skill",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.AFTER_GOAL),
        implies=("The wrapper call is preempted after the generated skill is installed.",),
        examples=("eclab install-develop-eclab-lab-skill ~/.codex",),
    )
    .annotate(
        "CONFIG_ROOT",
        commands=("install-develop-{short_product}-lab-skill",),
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
        "README.md",
        "Read destination safety, atomic replacement, backups, and refresh triggers.",
    )
    .refer("README.md", title="Generated skill installation guide")
)


@dataclass(frozen=True, slots=True)
class SkillInstallRequest:
    config_root: Path
    skill_name: str
    command: str
    request_id: str


class DevelopLabSkillPlugin(ExecutableWrapperPlugin):
    plugin_id = PLUGIN_ID
    priority = -900
    plugin_dependencies = (
        PluginDependency(
            SCHEMA_PLUGIN_ID,
            preprocess=DependencyPosition.AFTER,
            postprocess=DependencyPosition.BEFORE,
        ),
    )
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

    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        short_product = normalized_short_product(api.application)
        command = install_command(short_product)
        if not invocation.arguments or invocation.arguments[0] != command:
            request_schema_build(
                api,
                SchemaBuildRequest(self.plugin_id, uuid.uuid4().hex, required=False),
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
            skill_name(short_product),
            command,
            uuid.uuid4().hex,
        )
        api.set_context(INSTALL_REQUEST_CONTEXT, request)
        request_schema_build(
            api,
            SchemaBuildRequest(self.plugin_id, request.request_id, required=True),
        )
        return None

    def after_goal(
        self,
        invocation: Invocation,
        result: GoalResult[object],
        api: AfterGoalAPI,
    ) -> GoalResult[object]:
        del invocation
        request_value = api.get_context(INSTALL_REQUEST_CONTEXT)
        request = request_value if isinstance(request_value, SkillInstallRequest) else None
        bundle_value = api.get_context(SCHEMA_COMPILED_CONTEXT)
        bundle = bundle_value if isinstance(bundle_value, CompiledSchemaBundle) else None
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
        short_product = normalized_short_product(api.application)
        command = install_command(short_product)
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

    def _install(
        self,
        api: AfterGoalAPI,
        config_root: Path,
        name: str,
        bundle: CompiledSchemaBundle,
    ) -> Path:
        skills = config_root / "skills"
        if config_root.is_symlink() or not config_root.is_dir():
            raise ValueError(f"unsafe configuration root: {config_root}")
        if skills.is_symlink():
            raise ValueError(f"refusing symlinked skills directory: {skills}")
        skills.mkdir(parents=True, exist_ok=True)
        target = skills / name
        lease = hashlib.sha256(str(target).encode()).hexdigest()
        with api.lease(f"generated-skill:{lease}"):
            marker = _marker(target)
            if target.exists() or target.is_symlink():
                if target.is_symlink() or marker is None:
                    raise ValueError(f"refusing to replace unrecognized path: {target}")
                if marker.get("fingerprint") == bundle.fingerprint:
                    return target
            staged = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=skills))
            try:
                _write_static_skill(
                    staged,
                    name,
                    catalog_markdown=bundle.catalog_markdown,
                    fingerprint=bundle.fingerprint,
                )
                if target.is_dir():
                    previous_runtimes = target / "references" / "runtimes"
                    if previous_runtimes.is_dir() and not previous_runtimes.is_symlink():
                        shutil.copytree(
                            previous_runtimes,
                            staged / "references" / "runtimes",
                            dirs_exist_ok=True,
                        )
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
                        {"owner": PLUGIN_ID, "skill_name": name, "fingerprint": bundle.fingerprint},
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                if target.is_dir():
                    backups = skills / f".{name}-backups"
                    backups.mkdir(exist_ok=True)
                    backup = backups / f"{time.time_ns()}"
                    target.replace(backup)
                staged.replace(target)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
        return target


def install_command(short_product: str) -> str:
    return f"install-develop-{short_product}-lab-skill"


def skill_name(short_product: str) -> str:
    value = f"develop-{short_product}-lab"
    if len(value) > 63:
        raise ValueError("normalized skill name exceeds 63 characters")
    return value


def _write_static_skill(
    destination: Path,
    name: str,
    *,
    catalog_markdown: bytes | None = None,
    fingerprint: str | None = None,
) -> None:
    short_product = name.removeprefix("develop-").removesuffix("-lab")
    command = install_command(short_product)
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
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("owner") != PLUGIN_ID:
        return None
    return value


def _targets(state: StateStore) -> list[dict[str, str]]:
    if not state.exists(TARGETS_NAME):
        return []
    try:
        value = json.loads(state.read_text(TARGETS_NAME))
    except OSError, json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [
        {"config_root": item["config_root"], "skill_name": item["skill_name"]}
        for item in value
        if isinstance(item, dict)
        and isinstance(item.get("config_root"), str)
        and isinstance(item.get("skill_name"), str)
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
