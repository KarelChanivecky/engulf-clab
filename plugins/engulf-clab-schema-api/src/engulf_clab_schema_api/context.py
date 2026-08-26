from __future__ import annotations

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    InvocationAPI,
    PluginDependency,
)

from .builder import PluginSchema
from .models import (
    ECLAB_SCHEMA_PIPELINE_ID,
    CompiledSchemaBundle,
    ContainerlabSourceHint,
    RecordedPluginSchema,
    SchemaBuildRequest,
    SchemaContribution,
    SchemaDeclarationFailure,
    SchemaPipeline,
    SchemaRegistry,
    VrnetlabSourceHint,
)

SCHEMA_PLUGIN_ID = "engulf_clab.schema"
SCHEMA_REGISTRY_CONTEXT = "engulf_clab.schema.registry"
SCHEMA_SOURCE_CONTEXT = "engulf_clab.schema.containerlab_source"
SCHEMA_VRNETLAB_SOURCE_CONTEXT = "engulf_clab.schema.vrnetlab_source"
SCHEMA_VRNETLAB_PATH_CONTEXT = "engulf_clab.vrnetlab.path"
SCHEMA_REQUEST_CONTEXT = "engulf_clab.schema.requests"
SCHEMA_COMPILED_CONTEXT = "engulf_clab.schema.compiled"
SCHEMA_CONTEXTS = frozenset({SCHEMA_REGISTRY_CONTEXT})
SCHEMA_PLUGIN_DEPENDENCY = PluginDependency(
    SCHEMA_PLUGIN_ID,
    preprocess=DependencyPosition.AFTER,
    postprocess=None,
)


def schema_registry(api: InvocationAPI) -> SchemaRegistry:
    value = api.get_context(SCHEMA_REGISTRY_CONTEXT)
    if value is None:
        return SchemaRegistry()
    if not isinstance(value, SchemaRegistry):
        raise TypeError("invalid schema contribution registry")
    return value


def _commit_registry(api: BeforeGoalAPI, registry: SchemaRegistry) -> None:
    # The registry is a blackboard accumulated by every schema-declaring plugin in
    # before_goal but consumed only when an invocation compiles a schema (freeze,
    # destroy, and --help runs legitimately never do). Recording the value we just
    # wrote acknowledges the contribution, mirroring the schema plugin's
    # acknowledgement of terminal source inputs, so the runtime's unused-context
    # diagnostic does not fire on every non-compiling invocation.
    api.set_context(SCHEMA_REGISTRY_CONTEXT, registry)
    api.get_context(SCHEMA_REGISTRY_CONTEXT)


def record_schema_pipeline(api: BeforeGoalAPI, pipeline: SchemaPipeline) -> None:
    if not isinstance(pipeline, SchemaPipeline):
        raise TypeError("pipeline must be a SchemaPipeline")
    current = schema_registry(api)
    matching = tuple(item for item in current.pipelines if item.pipeline_id == pipeline.pipeline_id)
    if matching:
        if any(item != pipeline for item in matching):
            raise RuntimeError(f"conflicting schema pipeline declaration: {pipeline.pipeline_id}")
        return
    _commit_registry(api, SchemaRegistry((*current.pipelines, pipeline), current.contributions))


def record_plugin_schema(api: BeforeGoalAPI, schema: PluginSchema) -> None:
    current = schema_registry(api)
    try:
        entry: RecordedPluginSchema | SchemaDeclarationFailure = schema.snapshot(api.application)
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        api.logger.warning("schema contribution from %s is incomplete: %s", schema.plugin_id, error)
        entry = SchemaDeclarationFailure(schema.plugin_id, str(error))
    contribution = SchemaContribution(schema.pipeline_id, entry)
    _commit_registry(api, SchemaRegistry(current.pipelines, (*current.contributions, contribution)))


def publish_containerlab_source(
    api: BeforeGoalAPI | InvocationAPI, source: ContainerlabSourceHint
) -> None:
    api.set_context(SCHEMA_SOURCE_CONTEXT, source)


def publish_vrnetlab_source(api: BeforeGoalAPI | InvocationAPI, source: VrnetlabSourceHint) -> None:
    api.set_context(SCHEMA_VRNETLAB_SOURCE_CONTEXT, source)


def request_schema_build(api: BeforeGoalAPI, request: SchemaBuildRequest) -> None:
    current = api.get_context(SCHEMA_REQUEST_CONTEXT, ())
    if type(current) is not tuple or any(
        not isinstance(item, SchemaBuildRequest) for item in current
    ):
        raise RuntimeError("invalid schema build request registry")
    api.set_context(SCHEMA_REQUEST_CONTEXT, (*current, request))


def compiled_schema(
    api: InvocationAPI,
    pipeline_id: str = ECLAB_SCHEMA_PIPELINE_ID,
) -> CompiledSchemaBundle | None:
    SchemaPipeline(pipeline_id)
    value = api.get_context(SCHEMA_COMPILED_CONTEXT)
    if value is None:
        return None
    if not isinstance(value, CompiledSchemaBundle):
        raise TypeError("invalid compiled schema context")
    return value if value.pipeline_id == pipeline_id else None
