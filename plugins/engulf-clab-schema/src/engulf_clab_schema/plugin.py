from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from engulf_api import BeforeGoalAPI, GoalResult, Invocation, InvocationAPI, StateScope
from engulf_clab_schema_api import (
    ECLAB_SCHEMA_PIPELINE_ID,
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
    SchemaBackedPlugin,
    SchemaBuildRequest,
    SchemaContribution,
    SchemaPipeline,
    SchemaRegistry,
    ValueType,
    VrnetlabSourceHint,
    normalized_short_product,
    record_plugin_schema,
    record_schema_pipeline,
    schema_registry,
)
from engulf_executable_wrapper_api import HelpAPI, PreparedCallEvent

from .cache import (
    bundle_directory_complete,
    cache_record,
    cached_bundle_fingerprint,
    load_cached_bundle,
    schema_input_fingerprint,
)
from .compiler import compile_schema_bundle
from .node_kinds import resolve_node_kind_catalog
from .source import resolve_base_schema, source_hint_from_environment

PLUGIN_SCHEMA = (
    PluginSchema("engulf_clab.schema", package="engulf_clab_schema")
    .add_runtime_var(
        "CONTAINERLAB_SCHEMA",
        "Select an exact local Containerlab base schema; the matching CLI flag wins.",
        values=ValueType.FILE_PATH,
    )
    .add_cli_flag(
        "--eclab-containerlab-schema",
        "Use an exact local base schema for a binary-backed Containerlab build.",
        values=ValueType.FILE_PATH,
        environment="CONTAINERLAB_SCHEMA",
    )
    .annotate(
        "CONTAINERLAB_SCHEMA",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
        path_base=PathBase.INVOCATION_DIRECTORY,
        implies=("The supplied file is the complete base schema for the selected binary.",),
        examples=("CONTAINERLAB_SCHEMA=./schemas/clab.schema.json eclab deploy",),
    )
    .annotate(
        "--eclab-containerlab-schema",
        lifecycle=(LifecycleStage.BEFORE_GOAL, LifecycleStage.PREPARE_CALL),
        path_base=PathBase.INVOCATION_DIRECTORY,
        implies=("The supplied file is the complete base schema for the selected binary.",),
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
        "USAGE.md",
        "Read source selection, artifact layout, cache, and refresh behavior.",
    )
    .refer("USAGE.md", title="Runtime schema generator guide")
)


class SchemaGeneratorPlugin(SchemaBackedPlugin):
    plugin_id = "engulf_clab.schema"
    schema = PLUGIN_SCHEMA
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
        record_schema_pipeline(api, SchemaPipeline(ECLAB_SCHEMA_PIPELINE_ID))
        record_plugin_schema(api, PLUGIN_SCHEMA)
        requests = _requests(api)
        if not any(request.required for request in requests):
            # Source producers publish early so a later strict consumer can use
            # them. A non-strict invocation deliberately defers compilation to
            # prepare_call; acknowledge those terminal inputs even when a
            # wrapper-owned command preempts the inner call first.
            api.get_context(SCHEMA_SOURCE_CONTEXT)
            api.get_context(SCHEMA_VRNETLAB_SOURCE_CONTEXT)
            return None
        try:
            bundle = self._build(
                api,
                invocation.environment,
                strict=True,
                requests=requests,
            )
            if bundle is None:
                raise RuntimeError("strict schema generation returned no bundle")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            api.logger.error("failed to generate runtime schema: %s", error)
            return GoalResult.failed(1, error=str(error))
        api.set_context(SCHEMA_COMPILED_CONTEXT, bundle)
        return GoalResult.completed(bundle)

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        requests = _requests(api)
        if not requests:
            return
        try:
            bundle = self._build(
                api,
                event.environment,
                binary=event.binary,
                strict=False,
                requests=requests,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            api.logger.warning(
                "runtime schema refresh failed; retaining the last valid artifact: %s",
                error,
            )
            return
        if bundle is not None:
            api.set_context(SCHEMA_COMPILED_CONTEXT, bundle)

    def help(self, api: HelpAPI) -> str:
        del api
        return (
            "  --eclab-containerlab-schema FILE  Exact local base schema for a binary-backed "
            "private/offline build\n"
            "  CONTAINERLAB_SCHEMA is the persistent environment default; the CLI option wins.\n"
            "  Active plugin schemas are composed lazily and cached by runtime fingerprint."
        )

    def _build(
        self,
        api: BeforeGoalAPI | InvocationAPI,
        environment: Mapping[str, str],
        *,
        binary: str | Path | None = None,
        strict: bool,
        requests: tuple[SchemaBuildRequest, ...] = (),
    ) -> CompiledSchemaBundle | None:
        pipeline_id = _requested_pipeline(api, requests)
        lineage, contributions = _resolve_pipeline(schema_registry(api), pipeline_id)
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
            input_fingerprint = schema_input_fingerprint(
                api.application,
                contributions,
                source,
                vrnetlab_source,
                environment,
                pipeline_id=pipeline_id,
                pipeline_lineage=lineage,
            )
            if not strict:
                cached = cached_bundle_fingerprint(
                    state.directory,
                    input_fingerprint,
                    pipeline_id=pipeline_id,
                )
                if cached is not None:
                    if requests and all(
                        request.current_fingerprint == cached for request in requests
                    ):
                        api.logger.debug(
                            "runtime schema cache is current at %s; skipping generation",
                            cached,
                        )
                        return None
                    api.logger.debug("reusing cached runtime schema bundle %s", cached)
                    return load_cached_bundle(
                        state.directory,
                        cached,
                        pipeline_id=pipeline_id,
                    )
            base = resolve_base_schema(state, environment, source, refresh=strict)
            node_kinds = resolve_node_kind_catalog(
                state,
                environment,
                base,
                source,
                vrnetlab_source,
                refresh=strict,
            )
            bundle = compile_schema_bundle(
                api.application,
                base,
                contributions,
                node_kinds,
                pipeline_id=pipeline_id,
                pipeline_lineage=lineage,
            )
            _cache_bundle(state.directory, bundle, input_fingerprint)
        return bundle


def _requests(api: BeforeGoalAPI | InvocationAPI) -> tuple[SchemaBuildRequest, ...]:
    value = api.get_context(SCHEMA_REQUEST_CONTEXT, ())
    if type(value) is not tuple or any(not isinstance(item, SchemaBuildRequest) for item in value):
        raise TypeError("invalid schema build request registry")
    return value


def _requested_pipeline(
    api: BeforeGoalAPI | InvocationAPI,
    requests: tuple[SchemaBuildRequest, ...],
) -> str:
    if not requests:
        raise RuntimeError("schema generation requires at least one build request")
    pipeline_ids = {request.pipeline_id for request in requests}
    if len(pipeline_ids) != 1:
        raise RuntimeError("all schema build requests must select the same pipeline")
    pipeline_id = next(iter(pipeline_ids))
    running_pipeline = normalized_short_product(api.application)
    if pipeline_id != running_pipeline:
        raise RuntimeError(
            f"schema pipeline {pipeline_id} does not match running executable {running_pipeline}"
        )
    return pipeline_id


def _resolve_pipeline(
    registry: SchemaRegistry,
    pipeline_id: str,
) -> tuple[tuple[str, ...], tuple[SchemaContribution, ...]]:
    definitions: dict[str, SchemaPipeline] = {}
    for pipeline in registry.pipelines:
        existing = definitions.get(pipeline.pipeline_id)
        if existing is not None and existing != pipeline:
            raise RuntimeError(f"conflicting schema pipeline declaration: {pipeline.pipeline_id}")
        definitions[pipeline.pipeline_id] = pipeline

    reversed_lineage: list[str] = []
    seen: set[str] = set()
    current: str | None = pipeline_id
    while current is not None:
        if current in seen:
            raise RuntimeError(f"schema pipeline inheritance cycle includes {current}")
        seen.add(current)
        selected = definitions.get(current)
        if selected is None:
            raise RuntimeError(f"schema pipeline is not declared: {current}")
        reversed_lineage.append(current)
        current = selected.parent_pipeline_id
    lineage = tuple(reversed(reversed_lineage))

    contributions = tuple(
        contribution
        for member in lineage
        for contribution in registry.contributions
        if contribution.pipeline_id == member
    )
    providers: dict[str, str] = {}
    for contribution in contributions:
        previous = providers.get(contribution.plugin_id)
        if previous is not None:
            raise RuntimeError(
                f"duplicate schema provider {contribution.plugin_id} in resolved pipelines "
                f"{previous} and {contribution.pipeline_id}"
            )
        providers[contribution.plugin_id] = contribution.pipeline_id
    return lineage, contributions


def _cache_bundle(
    root: Path,
    bundle: CompiledSchemaBundle,
    input_fingerprint: str,
) -> None:
    pipeline_root = root / "pipelines" / bundle.pipeline_id
    artifacts = pipeline_root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    target = artifacts / bundle.fingerprint
    if not bundle_directory_complete(target, bundle.fingerprint):
        staged = Path(tempfile.mkdtemp(prefix=".schema-", dir=artifacts))
        displaced: Path | None = None
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
            if target.exists() or target.is_symlink():
                displaced = artifacts / f".{bundle.fingerprint}.invalid-{time.time_ns()}"
                target.replace(displaced)
            staged.replace(target)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
            if displaced is not None and displaced.exists():
                if not target.exists() and not target.is_symlink():
                    displaced.replace(target)
                elif displaced.is_dir() and not displaced.is_symlink():
                    shutil.rmtree(displaced)
                else:
                    displaced.unlink()
    latest = pipeline_root / "latest.json"
    temporary = pipeline_root / ".latest.json.tmp"
    temporary.write_bytes(
        cache_record(
            input_fingerprint,
            bundle.fingerprint,
            pipeline_id=bundle.pipeline_id,
            pipeline_lineage=bundle.pipeline_lineage,
        )
    )
    temporary.replace(latest)


plugin = SchemaGeneratorPlugin()
