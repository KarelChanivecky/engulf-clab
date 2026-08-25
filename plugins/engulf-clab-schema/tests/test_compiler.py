import hashlib
import json
from dataclasses import replace

import pytest
import yaml
from engulf_api import ApplicationMetadata
from engulf_clab_schema_api import (
    ExplainedValue,
    LifecycleStage,
    NodeKindDeclaration,
    OptionDeclaration,
    OptionKind,
    PluginOrdering,
    RecordedPluginSchema,
    ReferenceSnapshot,
    SchemaContribution,
    SchemaDeclarationFailure,
    SchemaScope,
    SemanticAnnotation,
    TaskRoute,
    ValueMode,
    ValueType,
)

from engulf_clab_schema.compiler import SchemaCompilationError, compile_schema_bundle
from engulf_clab_schema.node_kinds import NodeKindCatalog, NodeKindRecord, SourceIdentity
from engulf_clab_schema.source import BaseSchema

APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="ECLAB",
    vendor="Engulf",
    product="ECLAB",
    short_product_name="eclab",
    version="1.0",
)


def _base() -> BaseSchema:
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "topology": {
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "object",
                        "patternProperties": {
                            ".*": {"oneOf": [{"$ref": "#/definitions/node-config"}]}
                        },
                    },
                    "links": {"type": "array", "items": {"type": "object"}},
                },
            }
        },
        "definitions": {
            "node-config": {
                "type": "object",
                "properties": {"env": {"type": "object", "properties": {}}},
            }
        },
    }
    content = json.dumps(document).encode()
    return BaseSchema(
        document,
        content,
        "checkout",
        "https://example.test/clab",
        "abc",
        None,
        False,
        hashlib.sha256(content).hexdigest(),
    )


def _provider() -> RecordedPluginSchema:
    reference = b"details"
    return RecordedPluginSchema(
        "example.plugin",
        "example_plugin",
        "example-plugin",
        "1.2.3",
        (
            OptionDeclaration(
                OptionKind.RUNTIME_VAR,
                "EXAMPLE_SOURCE",
                "Persistent source default.",
                value_mode=ValueMode.TYPE,
                values=(ValueType.FILE_PATH.value,),
            ),
            OptionDeclaration(
                OptionKind.CLI_FLAG,
                "--example-source",
                "Select a source.",
                value_mode=ValueMode.TYPE,
                values=(ValueType.FILE_PATH.value,),
                environment="EXAMPLE_SOURCE",
            ),
            OptionDeclaration(
                OptionKind.NODE_VAR,
                "ECLAB_MODE_*",
                "Select a mode.",
                scope=SchemaScope.NODE,
                value_mode=ValueMode.TYPE,
                values=(ValueType.STRING.value,),
            ),
            OptionDeclaration(
                OptionKind.NODE_VAR,
                "ECLAB_EXACT",
                "Select an exact mode.",
                scope=SchemaScope.NODE,
                value_mode=ValueMode.TYPE,
                values=(ValueType.STRING.value,),
            ),
            OptionDeclaration(
                OptionKind.PROPERTY,
                "labels.example",
                "Enable the example.",
                scope=SchemaScope.NODE,
                value_mode=ValueMode.TYPE,
                values=(ValueType.BOOLEAN.value,),
            ),
            OptionDeclaration(
                OptionKind.PROPERTY,
                "image",
                "Select an image.",
                scope=SchemaScope.NODE,
                value_mode=ValueMode.TYPE,
                values=(ValueType.IMAGE_REFERENCE.value,),
                explained_values=(
                    ExplainedValue("example/helper", "Use the packaged helper node."),
                ),
            ),
        ),
        ("Use the example.",),
        ("Do not guess modes.",),
        (ReferenceSnapshot("README.md", None, reference, hashlib.sha256(reference).hexdigest()),),
        annotations=(
            SemanticAnnotation(
                "labels.example",
                commands=("deploy",),
                lifecycle=(LifecycleStage.PREPARE_CALL,),
                requires=("node.kind is linux",),
                examples=("example: true",),
            ),
        ),
        routes=(TaskRoute("enable-example", "README.md", "Read example behavior."),),
        ordering=(
            PluginOrdering(
                LifecycleStage.PREPARE_CALL,
                "Mutate before serialization.",
                before=("engulf_clab.lab_writer",),
            ),
        ),
    )


def test_compilation_is_deterministic_and_overlays_explicit_nodes() -> None:
    first = compile_schema_bundle(APPLICATION, _base(), (_provider(),))
    second = compile_schema_bundle(APPLICATION, _base(), (_provider(),))

    assert first.fingerprint == second.fingerprint
    manifest = json.loads(first.manifest)
    schema = json.loads(first.topology_schema)
    assert manifest["paths"]["node"]["env.ECLAB_MODE_*"][0]["plugin_id"] == "example.plugin"
    manifest_flag = manifest["plugins"][0]["options"][1]
    assert manifest["plugins"][0]["options"][0]["deprecated"] is False
    assert manifest["pipeline"] == {"id": "eclab", "lineage": ["eclab"]}
    assert manifest["plugins"][0]["pipeline_id"] == "eclab"
    assert manifest["plugins"][0]["inherited"] is False
    assert manifest_flag["environment_default"] == "EXAMPLE_SOURCE"
    node = schema["definitions"]["eclab-explicit-node-config"]
    assert "^ECLAB_MODE_.+$" in node["properties"]["env"]["patternProperties"]
    assert (
        node["properties"]["labels"]["properties"]["example"]["x-eclab-plugin-id"]
        == "example.plugin"
    )
    catalog = json.loads(first.catalog_json)
    assert catalog["tasks"]["enable-example"][0]["plugin_id"] == "example.plugin"
    provider = catalog["providers"][0]
    assert provider["schema"] == "plugins/example.plugin/schema.yaml"
    assert b"## Task routing" in first.catalog_markdown
    assert catalog["tasks"]["enable-example"][0]["schema"] == ("plugins/example.plugin/schema.yaml")
    assert len(first.plugin_schemas) == 1
    plugin_schema = first.plugin_schemas[0]
    assert plugin_schema.path == "schema.yaml"
    assert manifest["plugins"][0]["agent_schema"] == {
        "path": "plugins/example.plugin/schema.yaml",
        "sha256": plugin_schema.sha256,
    }
    capabilities = yaml.safe_load(plugin_schema.content)
    assert capabilities["plugin"]["id"] == "example.plugin"
    assert capabilities["plugin"]["pipeline_id"] == "eclab"
    assert capabilities["global_flags"]["--example-source"]["environment_default"] == (
        "EXAMPLE_SOURCE"
    )
    assert capabilities["topology"]["node"]["env"]["ECLAB_MODE_*"]["type"] == "string"
    assert capabilities["topology"]["node"]["properties"]["labels.example"]["requires"] == [
        "node.kind is linux"
    ]
    image = capabilities["topology"]["node"]["properties"]["image"]
    assert image["type"] == "image-reference"
    assert image["recognized_values"] == [
        {"value": "example/helper", "description": "Use the packaged helper node."}
    ]
    assert node["properties"]["image"]["type"] == "string"
    assert "enum" not in node["properties"]["image"]


def test_child_pipeline_manifest_and_catalog_include_inheritance_provenance() -> None:
    child = replace(_provider(), plugin_id="example.child")
    bundle = compile_schema_bundle(
        replace(APPLICATION, short_product_name="example-edition"),
        _base(),
        (
            SchemaContribution("eclab", _provider()),
            SchemaContribution("example-edition", child),
        ),
        pipeline_id="example-edition",
        pipeline_lineage=("eclab", "example-edition"),
    )

    manifest = json.loads(bundle.manifest)
    catalog = json.loads(bundle.catalog_json)
    providers = {item["plugin_id"]: item for item in manifest["plugins"]}
    catalog_providers = {item["plugin_id"]: item for item in catalog["providers"]}

    assert bundle.pipeline_id == "example-edition"
    assert bundle.pipeline_lineage == ("eclab", "example-edition")
    assert manifest["pipeline"] == {
        "id": "example-edition",
        "lineage": ["eclab", "example-edition"],
    }
    assert providers["example.plugin"]["inherited"] is True
    assert providers["example.child"]["inherited"] is False
    assert catalog_providers["example.plugin"]["pipeline_id"] == "eclab"
    assert catalog_providers["example.child"]["pipeline_id"] == "example-edition"
    assert json.loads(bundle.topology_schema)["x-eclab-schema-pipeline"] == "example-edition"


def test_referenced_node_objects_are_cloned_once_without_name_growth() -> None:
    base = _base()
    node = base.document["definitions"]["node-config"]
    node["properties"]["env"] = {"$ref": "#/definitions/env"}
    base.document["definitions"]["env"] = {
        "type": "object",
        "patternProperties": {".+": {"type": "string"}},
    }

    bundle = compile_schema_bundle(APPLICATION, base, (_provider(),))
    schema = json.loads(bundle.topology_schema)
    generated = [
        name for name in schema["definitions"] if name.startswith("eclab-node-final-parent")
    ]

    assert generated == ["eclab-node-final-parent-env"]
    assert "eclab-node-final-parent-eclab-node-final-parent" not in bundle.topology_schema.decode()
    properties = schema["definitions"][generated[0]]["properties"]
    assert "ECLAB_EXACT" in properties
    assert "^ECLAB_MODE_.+$" in schema["definitions"][generated[0]]["patternProperties"]


def test_failed_or_duplicate_contributors_are_rejected() -> None:
    with pytest.raises(SchemaCompilationError, match="incomplete"):
        compile_schema_bundle(
            APPLICATION, _base(), (SchemaDeclarationFailure("bad.plugin", "broken"),)
        )
    with pytest.raises(SchemaCompilationError, match="duplicate"):
        compile_schema_bundle(APPLICATION, _base(), (_provider(), _provider()))


def test_node_kind_catalog_and_plugin_augmentation_are_compiled() -> None:
    identity = SourceIdentity("checkout", "https://example.test/source", "abc", False, "1" * 64)
    node_kinds = NodeKindCatalog(
        identity,
        replace(identity, repository="https://example.test/vrnetlab", revision="def"),
        (
            NodeKindRecord(
                "linux",
                "Linux container",
                "docs/manual/kinds/linux.md",
                b"# Linux\n",
                None,
                None,
            ),
        ),
    )
    provider = replace(
        _provider(),
        node_kinds=(
            NodeKindDeclaration("linux", "Apply the example Linux conventions.", "README.md"),
        ),
    )

    bundle = compile_schema_bundle(APPLICATION, _base(), (provider,), node_kinds)

    catalog = json.loads(bundle.catalog_json)
    manifest = json.loads(bundle.manifest)
    assert catalog["node_kinds"]["schema"] == "plugins/containerlab.node_kinds/schema.yaml"
    assert catalog["node_kinds"]["count"] == 1
    assert manifest["node_kinds"]["vrnetlab"]["revision"] == "def"
    assert manifest["node_kinds"]["references"][0]["path"].startswith(
        "plugins/containerlab.node_kinds/node-kinds/linux/"
    )
    upstream = next(
        item for item in bundle.plugin_schemas if item.plugin_id == "containerlab.node_kinds"
    )
    index = yaml.safe_load(upstream.content)
    assert index["kinds"]["linux"]["schema"] == "node-kinds/linux/schema.yaml"
    kind_schema = next(
        item
        for item in bundle.references
        if item.plugin_id == "containerlab.node_kinds"
        and item.path == "node-kinds/linux/schema.yaml"
    )
    kind = yaml.safe_load(kind_schema.content)
    assert kind["augmentations"][0]["plugin_id"] == "example.plugin"
    assert b"## Node-kind routing" in bundle.catalog_markdown


def test_plugin_node_kind_must_exist_in_selected_containerlab_source() -> None:
    identity = SourceIdentity("checkout", None, None, False, "0" * 64)
    node_kinds = NodeKindCatalog(identity, identity, ())
    provider = replace(
        _provider(),
        node_kinds=(NodeKindDeclaration("missing", "Missing kind.", "README.md"),),
    )
    with pytest.raises(SchemaCompilationError, match="selected Containerlab"):
        compile_schema_bundle(APPLICATION, _base(), (provider,), node_kinds)
