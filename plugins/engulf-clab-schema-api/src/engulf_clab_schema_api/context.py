from __future__ import annotations

from engulf_api import (
    BeforeGoalAPI,
    DependencyPosition,
    InvocationAPI,
    PluginDependency,
)

from .builder import PluginSchema
from .models import (
    CompiledSchemaBundle,
    ContainerlabSourceHint,
    RecordedPluginSchema,
    SchemaBuildRequest,
    SchemaDeclarationFailure,
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


def record_plugin_schema(api: BeforeGoalAPI, schema: PluginSchema) -> None:
    current = api.get_context(SCHEMA_REGISTRY_CONTEXT, ())
    if type(current) is not tuple or any(
        not isinstance(item, (RecordedPluginSchema, SchemaDeclarationFailure)) for item in current
    ):
        raise RuntimeError("invalid schema contribution registry")
    try:
        entry: RecordedPluginSchema | SchemaDeclarationFailure = schema.snapshot(api.application)
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        api.logger.warning("schema contribution from %s is incomplete: %s", schema.plugin_id, error)
        entry = SchemaDeclarationFailure(schema.plugin_id, str(error))
    api.set_context(SCHEMA_REGISTRY_CONTEXT, (*current, entry))


def publish_containerlab_source(
    api: BeforeGoalAPI | InvocationAPI, source: ContainerlabSourceHint
) -> None:
    api.set_context(SCHEMA_SOURCE_CONTEXT, source)


def publish_vrnetlab_source(
    api: BeforeGoalAPI | InvocationAPI, source: VrnetlabSourceHint
) -> None:
    api.set_context(SCHEMA_VRNETLAB_SOURCE_CONTEXT, source)


def request_schema_build(api: BeforeGoalAPI, request: SchemaBuildRequest) -> None:
    current = api.get_context(SCHEMA_REQUEST_CONTEXT, ())
    if type(current) is not tuple or any(
        not isinstance(item, SchemaBuildRequest) for item in current
    ):
        raise RuntimeError("invalid schema build request registry")
    api.set_context(SCHEMA_REQUEST_CONTEXT, (*current, request))


def compiled_schema(api: InvocationAPI) -> CompiledSchemaBundle | None:
    value = api.get_context(SCHEMA_COMPILED_CONTEXT)
    if value is None:
        return None
    if not isinstance(value, CompiledSchemaBundle):
        raise TypeError("invalid compiled schema context")
    return value
