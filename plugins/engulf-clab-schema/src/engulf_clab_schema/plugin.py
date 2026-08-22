from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, InvocationAPI, StateScope
from engulf_clab_schema_api import (
    SCHEMA_COMPILED_CONTEXT,
    SCHEMA_REGISTRY_CONTEXT,
    SCHEMA_REQUEST_CONTEXT,
    SCHEMA_SOURCE_CONTEXT,
    SCHEMA_VRNETLAB_PATH_CONTEXT,
    SCHEMA_VRNETLAB_SOURCE_CONTEXT,
    CompiledSchemaBundle,
    ContainerlabSourceHint,
    LifecycleStage,
    PathBase,
    PluginSchema,
    RecordedPluginSchema,
    SchemaBuildRequest,
    SchemaDeclarationFailure,
    ValueType,
    VrnetlabSourceHint,
    record_plugin_schema,
)
from engulf_executable_wrapper_api import ExecutableWrapperPlugin, HelpAPI, PreparedCallEvent

from .compiler import compile_schema_bundle
from .node_kinds import resolve_node_kind_catalog
from .source import resolve_base_schema, source_hint_from_environment

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.schema", package="engulf_clab_schema")
    .add_runtime_var(
        "CONTAINERLAB_SCHEMA",
        "Use an exact local base schema for a binary-backed Containerlab build.",
        values=ValueType.FILE_PATH,
    )
    .annotate(
        "CONTAINERLAB_SCHEMA",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
        path_base=PathBase.INVOCATION_DIRECTORY,
        implies=("The supplied file is the complete base schema for the selected binary.",),
        examples=("CONTAINERLAB_SCHEMA=./schemas/clab.schema.json eclab deploy",),
    )
    .use_case("Describe the exact Containerlab source and active Engulf plugin controls.")
    .reject("Do not substitute an unrelated latest Containerlab schema for the selected source.")
    .order(
        LifecycleStage.BEFORE_GOAL,
        "The generator compiles only after every opted-in plugin has recorded its contribution.",
        after=("engulf_clab.develop_lab_skill",),
    )
    .route(
        "inspect-runtime-schema",
        "README.md",
        "Read source selection, artifact layout, cache, and refresh behavior.",
    )
    .refer("README.md", title="Runtime schema generator guide")
)


class SchemaGeneratorPlugin(ExecutableWrapperPlugin):
    plugin_id = "engulf_clab.schema"
    priority = -1000
    context_reads = frozenset(
        {SCHEMA_REGISTRY_CONTEXT, SCHEMA_SOURCE_CONTEXT, SCHEMA_REQUEST_CONTEXT}
        | {SCHEMA_VRNETLAB_SOURCE_CONTEXT, SCHEMA_VRNETLAB_PATH_CONTEXT}
    )
    context_writes = frozenset({SCHEMA_REGISTRY_CONTEXT, SCHEMA_COMPILED_CONTEXT})

    def before_goal(
        self,
        invocation: Invocation,
        api: BeforeGoalAPI,
    ) -> GoalResult[object] | None:
        record_plugin_schema(api, PLUGIN_SCHEMA)
        requests = _requests(api)
        if not any(request.required for request in requests):
            return None
        try:
            bundle = self._build(api, invocation.environment, strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            api.logger.error("failed to generate runtime schema: %s", error)
            return GoalResult.failed(1, error=str(error))
        api.set_context(SCHEMA_COMPILED_CONTEXT, bundle)
        return GoalResult.completed(bundle)

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if not _requests(api):
            return
        try:
            bundle = self._build(api, os.environ, binary=event.binary, strict=False)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            api.logger.warning(
                "runtime schema refresh failed; retaining the last valid artifact: %s",
                error,
            )
            return
        api.set_context(SCHEMA_COMPILED_CONTEXT, bundle)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  CONTAINERLAB_SCHEMA  Exact local base schema for a binary-backed "
            "private/offline build\n"
            "  Active plugin schemas are composed lazily and cached by runtime fingerprint."
        )

    def _build(
        self,
        api: BeforeGoalAPI | InvocationAPI,
        environment: Mapping[str, str],
        *,
        binary: str | Path | None = None,
        strict: bool,
    ) -> CompiledSchemaBundle:
        current = api.get_context(SCHEMA_REGISTRY_CONTEXT, ())
        if type(current) is not tuple or any(
            not isinstance(item, (RecordedPluginSchema, SchemaDeclarationFailure))
            for item in current
        ):
            raise RuntimeError("invalid schema contribution registry")
        source = api.get_context(SCHEMA_SOURCE_CONTEXT)
        if source is None:
            source = source_hint_from_environment(environment, binary=binary)
        if not isinstance(source, ContainerlabSourceHint):
            raise TypeError("invalid Containerlab schema source hint")
        vrnetlab_source = api.get_context(SCHEMA_VRNETLAB_SOURCE_CONTEXT)
        if vrnetlab_source is not None and not isinstance(vrnetlab_source, VrnetlabSourceHint):
            raise TypeError("invalid vrnetlab schema source hint")
        if vrnetlab_source is None:
            prepared_vrnetlab = api.get_context(SCHEMA_VRNETLAB_PATH_CONTEXT)
            if prepared_vrnetlab is not None:
                if not isinstance(prepared_vrnetlab, str):
                    raise TypeError("invalid prepared vrnetlab checkout context")
                vrnetlab_source = VrnetlabSourceHint(checkout=Path(prepared_vrnetlab))
        state = api.state(StateScope.USER)
        with api.lease("containerlab-runtime-schema"):
            base = resolve_base_schema(state, environment, source, refresh=strict)
            node_kinds = resolve_node_kind_catalog(
                state,
                environment,
                base,
                source,
                vrnetlab_source,
                refresh=strict,
            )
            bundle = compile_schema_bundle(api.application, base, current, node_kinds)
            _cache_bundle(state.directory, bundle)
        return bundle


def _requests(api: BeforeGoalAPI | InvocationAPI) -> tuple[SchemaBuildRequest, ...]:
    value = api.get_context(SCHEMA_REQUEST_CONTEXT, ())
    if type(value) is not tuple or any(not isinstance(item, SchemaBuildRequest) for item in value):
        raise TypeError("invalid schema build request registry")
    return value


def _cache_bundle(root: Path, bundle: CompiledSchemaBundle) -> None:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    target = artifacts / bundle.fingerprint
    if not target.is_dir():
        staged = Path(tempfile.mkdtemp(prefix=".schema-", dir=artifacts))
        try:
            (staged / "manifest.json").write_bytes(bundle.manifest)
            (staged / "clab.schema.json").write_bytes(bundle.topology_schema)
            (staged / "catalog.json").write_bytes(bundle.catalog_json)
            (staged / "catalog.md").write_bytes(bundle.catalog_markdown)
            for plugin_schema in bundle.plugin_schemas:
                destination = staged / "plugins" / plugin_schema.plugin_id / plugin_schema.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(plugin_schema.content)
            for reference in bundle.references:
                destination = staged / "plugins" / reference.plugin_id / reference.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(reference.content)
            staged.replace(target)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    latest = root / "latest.json"
    temporary = root / ".latest.json.tmp"
    temporary.write_text(
        json.dumps({"fingerprint": bundle.fingerprint}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(latest)


plugin = SchemaGeneratorPlugin()
