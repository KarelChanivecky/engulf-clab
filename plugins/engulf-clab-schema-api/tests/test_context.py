from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

import pytest
from engulf_api import ApplicationMetadata

from engulf_clab_schema_api import (
    ECLAB_SCHEMA_PIPELINE_ID,
    SCHEMA_COMPILED_CONTEXT,
    SCHEMA_REGISTRY_CONTEXT,
    CompiledSchemaBundle,
    PluginSchema,
    SchemaBuildRequest,
    SchemaPipeline,
    SchemaRegistry,
    compiled_schema,
    record_plugin_schema,
    record_schema_pipeline,
    schema_registry,
)

APPLICATION = ApplicationMetadata(
    application_id="example-edition",
    display_name="Example Edition",
    vendor="Example",
    product="Example Containerlab",
    short_product_name="example-edition",
    version="1.0",
)


class _API:
    def __init__(self) -> None:
        self.application = APPLICATION
        self.logger = Mock()
        self.context: dict[str, object] = {}

    def get_context(self, context_id: str, default: object = None) -> object:
        return self.context.get(context_id, default)

    def set_context(
        self, context_id: str, value: object, **_kwargs: object
    ) -> None:
        self.context[context_id] = value


def test_registry_is_partitioned_and_expands_against_running_application() -> None:
    api = _API()
    typed_api = cast(Any, api)
    record_schema_pipeline(typed_api, SchemaPipeline("example-edition", "eclab"))
    schema = (
        PluginSchema(
            "example.pipeline",
            package="engulf_clab_schema",
            pipeline_id="example-edition",
        )
        .add_command("run-{short_product}", "Run the edition command.")
        .refer("README.md")
    )

    record_plugin_schema(typed_api, schema)

    registry = schema_registry(typed_api)
    assert registry.pipelines == (
        SchemaPipeline(ECLAB_SCHEMA_PIPELINE_ID),
        SchemaPipeline("example-edition", ECLAB_SCHEMA_PIPELINE_ID),
    )
    assert registry.contributions[0].pipeline_id == "example-edition"
    entry = registry.contributions[0].entry
    assert entry.options[0].name == "run-example-edition"


def test_pipeline_declarations_are_idempotent_but_conflicts_are_rejected() -> None:
    api = _API()
    typed_api = cast(Any, api)
    pipeline = SchemaPipeline("example-edition", ECLAB_SCHEMA_PIPELINE_ID)
    record_schema_pipeline(typed_api, pipeline)
    record_schema_pipeline(typed_api, pipeline)
    with pytest.raises(RuntimeError, match="conflicting"):
        record_schema_pipeline(typed_api, SchemaPipeline("example-edition", "another"))


@pytest.mark.parametrize("pipeline_id", ["Example", "two_words", "-leading", "two--parts"])
def test_pipeline_ids_must_already_be_normalized(pipeline_id: str) -> None:
    with pytest.raises(ValueError, match="lowercase normalized"):
        SchemaPipeline(pipeline_id)


def test_requests_and_compiled_lookup_are_pipeline_aware() -> None:
    assert SchemaBuildRequest("example.consumer", "one").pipeline_id == ECLAB_SCHEMA_PIPELINE_ID
    request = SchemaBuildRequest(
        "example.consumer",
        "two",
        pipeline_id="example-edition",
    )
    assert request.pipeline_id == "example-edition"

    bundle = CompiledSchemaBundle(
        "a" * 64,
        b"{}",
        b"{}",
        b"{}",
        b"",
        (),
        pipeline_id="example-edition",
        pipeline_lineage=("eclab", "example-edition"),
    )
    api = _API()
    api.context[SCHEMA_COMPILED_CONTEXT] = bundle
    typed_api = cast(Any, api)
    assert compiled_schema(typed_api, "example-edition") is bundle
    assert compiled_schema(typed_api) is None


def test_registry_context_rejects_the_legacy_unpartitioned_tuple() -> None:
    api = _API()
    api.context[SCHEMA_REGISTRY_CONTEXT] = ()
    with pytest.raises(TypeError, match="invalid schema contribution registry"):
        schema_registry(cast(Any, api))
    assert isinstance(SchemaRegistry(), SchemaRegistry)
