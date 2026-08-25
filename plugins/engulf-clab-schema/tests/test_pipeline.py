from __future__ import annotations

from typing import Any, cast

import pytest
from engulf_api import ApplicationMetadata
from engulf_clab_schema_api import (
    ECLAB_SCHEMA_PIPELINE_ID,
    RecordedPluginSchema,
    SchemaBuildRequest,
    SchemaContribution,
    SchemaDeclarationFailure,
    SchemaPipeline,
    SchemaRegistry,
)

from engulf_clab_schema.plugin import _requested_pipeline, _resolve_pipeline

APPLICATION = ApplicationMetadata(
    application_id="example-edition",
    display_name="Example Edition",
    vendor="Example",
    product="Example Containerlab",
    short_product_name="example-edition",
    version="1.0",
)


def _provider(plugin_id: str) -> RecordedPluginSchema:
    return RecordedPluginSchema(plugin_id, "example", "example", "1.0", (), (), (), ())


def _registry(*contributions: SchemaContribution) -> SchemaRegistry:
    return SchemaRegistry(
        (
            SchemaPipeline(ECLAB_SCHEMA_PIPELINE_ID),
            SchemaPipeline("example-edition", ECLAB_SCHEMA_PIPELINE_ID),
            SchemaPipeline("unrelated"),
        ),
        contributions,
    )


def test_base_excludes_child_and_child_inherits_each_provider_once() -> None:
    base = SchemaContribution("eclab", _provider("example.base"))
    child = SchemaContribution("example-edition", _provider("example.child"))
    unrelated_failure = SchemaContribution(
        "unrelated", SchemaDeclarationFailure("example.unrelated", "broken")
    )
    registry = _registry(base, child, unrelated_failure)

    base_lineage, base_entries = _resolve_pipeline(registry, "eclab")
    child_lineage, child_entries = _resolve_pipeline(registry, "example-edition")

    assert base_lineage == ("eclab",)
    assert [item.plugin_id for item in base_entries] == ["example.base"]
    assert child_lineage == ("eclab", "example-edition")
    assert [item.plugin_id for item in child_entries] == ["example.base", "example.child"]


def test_resolution_rejects_missing_parent_cycle_conflict_and_duplicate_provider() -> None:
    missing = SchemaRegistry((SchemaPipeline("example-edition", "missing"),), ())
    with pytest.raises(RuntimeError, match="not declared: missing"):
        _resolve_pipeline(missing, "example-edition")

    cycle = SchemaRegistry(
        (SchemaPipeline("one", "two"), SchemaPipeline("two", "one")),
        (),
    )
    with pytest.raises(RuntimeError, match="cycle"):
        _resolve_pipeline(cycle, "one")

    conflict = SchemaRegistry(
        (
            SchemaPipeline("example-edition", "eclab"),
            SchemaPipeline("example-edition", "other"),
        ),
        (),
    )
    with pytest.raises(RuntimeError, match="conflicting"):
        _resolve_pipeline(conflict, "example-edition")

    duplicate = _registry(
        SchemaContribution("eclab", _provider("example.same")),
        SchemaContribution("example-edition", _provider("example.same")),
    )
    with pytest.raises(RuntimeError, match="duplicate schema provider"):
        _resolve_pipeline(duplicate, "example-edition")


class _API:
    application = APPLICATION


def test_requests_select_one_pipeline_matching_the_running_executable() -> None:
    api = cast(Any, _API())
    selected = _requested_pipeline(
        api,
        (
            SchemaBuildRequest("example.one", "one", pipeline_id="example-edition"),
            SchemaBuildRequest("example.two", "two", pipeline_id="example-edition"),
        ),
    )
    assert selected == "example-edition"

    with pytest.raises(RuntimeError, match="same pipeline"):
        _requested_pipeline(
            api,
            (
                SchemaBuildRequest("example.one", "one", pipeline_id="example-edition"),
                SchemaBuildRequest("example.two", "two", pipeline_id="eclab"),
            ),
        )
    with pytest.raises(RuntimeError, match="does not match running executable"):
        _requested_pipeline(api, (SchemaBuildRequest("example.one", "one"),))
