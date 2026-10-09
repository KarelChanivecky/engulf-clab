from __future__ import annotations

import atexit
import importlib.resources
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from engulf_api import (
    AfterGoalAPI,
    ApplicationMetadata,
    BeforeGoalAPI,
    GoalResult,
    Invocation,
    RegistrationAPI,
    StateScope,
)
from engulf_clab_schema import bundle_directory_complete
from engulf_clab_schema_api import (
    ECLAB_SCHEMA_PIPELINE_ID,
    SCHEMA_COMPILED_CONTEXT,
    SCHEMA_REGISTRY_CONTEXT,
    SCHEMA_REQUEST_CONTEXT,
    CompiledSchemaBundle,
    PluginSchema,
    SchemaAudience,
    SchemaBackedPlugin,
    SchemaBuildRequest,
    compiled_schema,
    normalized_short_product,
    record_plugin_schema,
    request_schema_build,
)
from engulf_clab_skill_api import (
    SKILL_PATHS_CONTEXT,
    SKILL_TEMPORARY_PATHS_CONTEXT,
    SKILL_TRACKED_TARGETS_CONTEXT,
    publish_tracked_skill_targets,
    record_temporary_skill,
    tracked_skill_targets,
)
from engulf_executable_wrapper_api import ArgumentRegistry, CompletionRegistry

PLUGIN_ID = "engulf_clab.develop_lab_skill"
ECLAB_SHORT_PRODUCT = ECLAB_SCHEMA_PIPELINE_ID
ECLAB_INSTALL_COMMAND = "install-skills"
LEGACY_INSTALL_COMMAND = "install-develop-eclab-lab-skill"
ECLAB_SKILL_NAME = "develop-eclab-lab"
LEGACY_TARGETS_NAME = "targets.json"
LEGACY_MARKER_NAME = ".engulf-clab-generated.json"
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_PROCESS_TOKEN = uuid.uuid4().hex
_PROCESS_ROOT_MAX_AGE_SECONDS = 24 * 60 * 60
_GENERATED_PROCESS_ROOTS: set[Path] = set()
_GENERATED_PROCESS_ROOTS_LOCK = threading.Lock()

PLUGIN_SCHEMA = (
    PluginSchema(
        PLUGIN_ID,
        package="engulf_clab_develop_lab_skill",
        audience=SchemaAudience.SUPPORT,
    )
    .use_case("Install current eclab plugin guidance as the develop-eclab-lab skill.")
    .reject("Do not use this eclab skill for a different launcher or schema pipeline.")
    .refer("USAGE.md", title="Generated skill installation guide")
)


class DevelopLabSkillPlugin(SchemaBackedPlugin):
    plugin_id = PLUGIN_ID
    schema = PLUGIN_SCHEMA
    priority = -900
    context_reads = (
        frozenset(
            {
                SCHEMA_REGISTRY_CONTEXT,
                SCHEMA_REQUEST_CONTEXT,
                SCHEMA_COMPILED_CONTEXT,
            }
        )
        | frozenset(
            {
                SKILL_PATHS_CONTEXT,
                SKILL_TRACKED_TARGETS_CONTEXT,
                SKILL_TEMPORARY_PATHS_CONTEXT,
            }
        )
    )
    context_writes = frozenset(
        {SCHEMA_REGISTRY_CONTEXT, SCHEMA_REQUEST_CONTEXT}
    ) | frozenset(
        {SKILL_PATHS_CONTEXT, SKILL_TRACKED_TARGETS_CONTEXT, SKILL_TEMPORARY_PATHS_CONTEXT}
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
        if (
            invocation.arguments
            and invocation.arguments[0] in {install_command(), LEGACY_INSTALL_COMMAND}
            and ("--help" in invocation.arguments or "-h" in invocation.arguments)
        ):
            return None
        explicit = _explicit_install(invocation.arguments)
        current_fingerprint: str | None = None
        if not explicit:
            if _skip_automatic_refresh(invocation.arguments, invocation.environment):
                return None
            legacy_targets = _legacy_tracked_targets(api)
            if legacy_targets:
                publish_tracked_skill_targets(api, legacy_targets)
            targets = tuple(
                path for path in tracked_skill_targets(api) if path.name == ECLAB_SKILL_NAME
            )
            if not targets:
                return None
            fingerprints = tuple(_installed_fingerprint(path) for path in targets)
            if (
                fingerprints
                and fingerprints[0] is not None
                and all(item == fingerprints[0] for item in fingerprints)
            ):
                current_fingerprint = fingerprints[0]
        request_schema_build(
            api,
            SchemaBuildRequest(
                self.plugin_id,
                uuid.uuid4().hex,
                required=explicit,
                current_fingerprint=current_fingerprint,
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
        if not _is_eclab_application(api.application):
            return result
        explicit = _explicit_install(invocation.arguments)
        bundle = compiled_schema(api, ECLAB_SCHEMA_PIPELINE_ID)
        if bundle is None:
            if explicit and result.exit_code == 0:
                return GoalResult.failed(1, error="schema generator produced no skill bundle")
            return result
        if explicit or any(
            path.name == ECLAB_SKILL_NAME for path in tracked_skill_targets(api)
        ):
            try:
                with api.lease("develop-lab-skill-source"):
                    source = _write_generated_skill(api, bundle)
                try:
                    record_temporary_skill(api, source)
                except BaseException:
                    _remove_generated_source(source.parent)
                    raise
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                if explicit:
                    api.logger.error("failed to prepare generated lab skill: %s", error)
                    return GoalResult.failed(1, error=str(error))
                api.logger.warning("automatic lab skill refresh preparation skipped: %s", error)
        return result

def install_command() -> str:
    return ECLAB_INSTALL_COMMAND


def _explicit_install(arguments: tuple[str, ...]) -> bool:
    return bool(
        arguments
        and arguments[0] in {install_command(), LEGACY_INSTALL_COMMAND}
        and "--help" not in arguments
        and "-h" not in arguments
    )


def skill_name() -> str:
    return ECLAB_SKILL_NAME


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


def _installed_fingerprint(target: Path) -> str | None:
    current_path = target / "references" / "current.json"
    if current_path.is_symlink() or not current_path.is_file():
        return None
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(current, dict)
        or current.get("pipeline_id") != ECLAB_SCHEMA_PIPELINE_ID
        or not isinstance(current.get("fingerprint"), str)
    ):
        return None
    fingerprint = current["fingerprint"]
    runtime = target / "references" / "runtimes" / fingerprint
    return (
        fingerprint
        if _FINGERPRINT.fullmatch(fingerprint)
        and bundle_directory_complete(
            runtime,
            fingerprint,
            pipeline_id=ECLAB_SCHEMA_PIPELINE_ID,
        )
        else None
    )


def _legacy_tracked_targets(api: BeforeGoalAPI) -> tuple[Path, ...]:
    state = api.state(StateScope.USER)
    if not state.exists(LEGACY_TARGETS_NAME):
        return ()
    try:
        records = json.loads(state.read_text(LEGACY_TARGETS_NAME))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(records, list):
        return ()
    targets: set[Path] = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("config_root"), str)
            or record.get("skill_name") != ECLAB_SKILL_NAME
        ):
            continue
        target = Path(record["config_root"]) / "skills" / ECLAB_SKILL_NAME
        marker_path = target / LEGACY_MARKER_NAME
        if target.is_symlink() or marker_path.is_symlink() or not target.is_dir():
            continue
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(marker, dict)
            and marker.get("skill_name") == ECLAB_SKILL_NAME
            and marker.get("owner") in {PLUGIN_ID, "engulf_clab.skill_collector"}
        ):
            targets.add(target.resolve())
    return tuple(sorted(targets))


def _write_generated_skill(api: AfterGoalAPI, bundle: CompiledSchemaBundle) -> Path:
    if bundle.pipeline_id != ECLAB_SCHEMA_PIPELINE_ID:
        raise ValueError(f"cannot render {bundle.pipeline_id} as the eclab development skill")
    if not _FINGERPRINT.fullmatch(bundle.fingerprint):
        raise ValueError("schema compiler returned an invalid fingerprint")
    state = api.state(StateScope.USER)
    generated = state.directory / "generated-skills"
    if generated.is_symlink():
        raise ValueError(f"refusing symlinked generated skill directory: {generated}")
    generated.mkdir(exist_ok=True)
    process_root = _generated_process_root(generated)
    invocation_root = process_root / uuid.uuid4().hex
    invocation_root.mkdir()
    target = invocation_root / ECLAB_SKILL_NAME
    staged = Path(tempfile.mkdtemp(prefix=f".{ECLAB_SKILL_NAME}.", dir=invocation_root))
    try:
        _write_static_skill(
            staged,
            catalog_markdown=bundle.catalog_markdown,
            fingerprint=bundle.fingerprint,
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
        staged.replace(target)
        return target.resolve()
    except BaseException:
        _remove_generated_source(invocation_root)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def _remove_generated_source(directory: Path) -> None:
    if directory.is_symlink():
        return
    if directory.is_dir():
        shutil.rmtree(directory)


def _generated_process_root(generated: Path) -> Path:
    pid = os.getpid()
    name = f"process-{pid}-{_PROCESS_TOKEN}"
    with _GENERATED_PROCESS_ROOTS_LOCK:
        _prune_stale_generated_processes(generated, keep=name)
        root = generated / name
        if root.is_symlink():
            raise ValueError(f"refusing symlinked generated skill process directory: {root}")
        root.mkdir(exist_ok=True)
        owner = root / ".owner.json"
        if owner.is_symlink():
            raise ValueError(f"refusing symlinked generated skill owner file: {owner}")
        expected = {"pid": pid, "token": _PROCESS_TOKEN}
        if owner.exists():
            try:
                current = json.loads(owner.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError(f"invalid generated skill owner file: {owner}") from error
            if current != expected:
                raise RuntimeError(f"generated skill process directory has a different owner: {root}")
        else:
            owner.write_text(json.dumps(expected, sort_keys=True) + "\n", encoding="utf-8")
        os.utime(root, None)
        _GENERATED_PROCESS_ROOTS.add(root)
        return root


def _prune_stale_generated_processes(generated: Path, *, keep: str) -> None:
    now = time.time()
    for root in generated.iterdir():
        if root.name == keep:
            continue
        if root.is_symlink() or not root.is_dir():
            continue
        age = now - root.stat().st_mtime
        if _FINGERPRINT.fullmatch(root.name):
            if age > _PROCESS_ROOT_MAX_AGE_SECONDS:
                _remove_generated_source(root)
            continue
        if not root.name.startswith("process-"):
            continue
        owner = root / ".owner.json"
        pid: int | None = None
        if owner.is_file() and not owner.is_symlink():
            try:
                value = json.loads(owner.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = None
            if isinstance(value, dict) and type(value.get("pid")) is int:
                pid = value["pid"]
        if (pid is not None and pid > 0 and not _process_is_alive(pid)) or age > (
            _PROCESS_ROOT_MAX_AGE_SECONDS
        ):
            _remove_generated_source(root)


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _cleanup_generated_process_roots() -> None:
    with _GENERATED_PROCESS_ROOTS_LOCK:
        roots = tuple(_GENERATED_PROCESS_ROOTS)
        _GENERATED_PROCESS_ROOTS.clear()
    for root in roots:
        _remove_generated_source(root)


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


plugin = DevelopLabSkillPlugin()
atexit.register(_cleanup_generated_process_roots)
