import json
from pathlib import Path

from engulf_api import ApplicationMetadata
from engulf_clab_schema_api import (
    CompiledPluginSchema,
    CompiledReference,
    CompiledSchemaBundle,
    ContainerlabSourceHint,
    ContainerlabSourceKind,
    RecordedPluginSchema,
    SchemaDeclarationFailure,
    VrnetlabSourceHint,
)

from engulf_clab_schema.cache import (
    bundle_directory_complete,
    cached_bundle_fingerprint,
    load_cached_bundle,
    schema_input_fingerprint,
)
from engulf_clab_schema.plugin import _cache_bundle

APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="ECLAB",
    vendor="Engulf",
    product="ECLAB",
    short_product_name="eclab",
    version="1.0",
)


def test_input_fingerprint_tracks_installed_distribution_versions() -> None:
    source = ContainerlabSourceHint(
        ContainerlabSourceKind.REPOSITORY,
        repository="https://example.invalid/containerlab",
        revision="commit-one",
    )
    vrnetlab = VrnetlabSourceHint(
        repository="https://example.invalid/vrnetlab",
        revision="commit-two",
    )

    def provider(version: str) -> RecordedPluginSchema:
        return RecordedPluginSchema(
            "example.plugin",
            "example_plugin",
            "example-plugin",
            version,
            (),
            (),
            (),
            (),
        )

    first = schema_input_fingerprint(APPLICATION, (provider("1.0"),), source, vrnetlab, {})
    second = schema_input_fingerprint(APPLICATION, (provider("1.1"),), source, vrnetlab, {})
    assert first != second


def test_input_fingerprint_changes_with_schema_plugins_and_source_files(tmp_path: Path) -> None:
    containerlab = tmp_path / "containerlab"
    schema = containerlab / "schemas" / "clab.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text('{"properties": {}}\n')
    kinds = containerlab / "docs" / "manual" / "kinds"
    kinds.mkdir(parents=True)
    (kinds / "linux.md").write_text("Linux one\n")

    vrnetlab = tmp_path / "vrnetlab"
    common = vrnetlab / "common"
    common.mkdir(parents=True)
    (common / "vrnetlab.py").write_text("# runtime\n")
    product = vrnetlab / "vendor" / "product"
    product.mkdir(parents=True)
    (product / "README.md").write_text("Product one\n")

    containerlab_hint = ContainerlabSourceHint(
        ContainerlabSourceKind.CHECKOUT,
        checkout=containerlab,
    )
    vrnetlab_hint = VrnetlabSourceHint(checkout=vrnetlab)
    entries = (SchemaDeclarationFailure("example.plugin", "unavailable"),)

    first = schema_input_fingerprint(
        APPLICATION,
        entries,
        containerlab_hint,
        vrnetlab_hint,
        {},
    )
    assert first == schema_input_fingerprint(
        APPLICATION,
        entries,
        containerlab_hint,
        vrnetlab_hint,
        {},
    )

    schema.write_text('{"properties": {"name": {}}}\n')
    source_changed = schema_input_fingerprint(
        APPLICATION,
        entries,
        containerlab_hint,
        vrnetlab_hint,
        {},
    )
    assert source_changed != first
    (product / "README.md").write_text("Product documentation changed\n")
    documentation_changed = schema_input_fingerprint(
        APPLICATION,
        entries,
        containerlab_hint,
        vrnetlab_hint,
        {},
    )
    assert documentation_changed != source_changed
    assert (
        schema_input_fingerprint(
            APPLICATION,
            (SchemaDeclarationFailure("example.plugin", "changed"),),
            containerlab_hint,
            vrnetlab_hint,
            {},
        )
        != documentation_changed
    )


def test_cached_bundle_is_reused_and_incomplete_artifacts_are_repaired(tmp_path: Path) -> None:
    fingerprint = "a" * 64
    manifest = {
        "fingerprint": fingerprint,
        "pipeline": {"id": "eclab", "lineage": ["eclab"]},
        "plugins": [
            {
                "plugin_id": "example.plugin",
                "agent_schema": {"path": "plugins/example.plugin/schema.yaml"},
                "references": [{"path": "README.md"}],
            }
        ],
        "node_kinds": None,
    }
    bundle = CompiledSchemaBundle(
        fingerprint=fingerprint,
        manifest=(json.dumps(manifest) + "\n").encode(),
        topology_schema=b"{}\n",
        catalog_json=b"{}\n",
        catalog_markdown=b"# Catalog\n",
        plugin_schemas=(
            CompiledPluginSchema(
                "example.plugin",
                "schema.yaml",
                b"format: example\n",
                "schema-sha",
            ),
        ),
        references=(
            CompiledReference(
                "example.plugin",
                "README.md",
                "Example",
                b"# Example\n",
                "reference-sha",
            ),
        ),
    )

    _cache_bundle(tmp_path, bundle, "inputs-one")
    target = tmp_path / "pipelines" / "eclab" / "artifacts" / fingerprint
    assert bundle_directory_complete(target, fingerprint)
    assert cached_bundle_fingerprint(tmp_path, "inputs-one") == fingerprint
    assert cached_bundle_fingerprint(tmp_path, "inputs-two") is None

    loaded = load_cached_bundle(tmp_path, fingerprint)
    assert loaded.fingerprint == fingerprint
    assert {item.path for item in loaded.references} == {"README.md"}
    assert {item.path for item in loaded.plugin_schemas} == {"schema.yaml"}

    (target / "plugins" / "example.plugin" / "README.md").unlink()
    assert cached_bundle_fingerprint(tmp_path, "inputs-one") is None
    _cache_bundle(tmp_path, bundle, "inputs-one")
    assert bundle_directory_complete(target, fingerprint)


def test_pipeline_caches_are_isolated_and_legacy_unscoped_cache_is_ignored(
    tmp_path: Path,
) -> None:
    fingerprint = "c" * 64

    def bundle(pipeline_id: str, lineage: tuple[str, ...]) -> CompiledSchemaBundle:
        manifest = {
            "fingerprint": fingerprint,
            "pipeline": {"id": pipeline_id, "lineage": list(lineage)},
            "plugins": [],
            "node_kinds": None,
        }
        return CompiledSchemaBundle(
            fingerprint=fingerprint,
            manifest=(json.dumps(manifest) + "\n").encode(),
            topology_schema=b"{}\n",
            catalog_json=b"{}\n",
            catalog_markdown=b"# Catalog\n",
            references=(),
            pipeline_id=pipeline_id,
            pipeline_lineage=lineage,
        )

    _cache_bundle(tmp_path, bundle("eclab", ("eclab",)), "same-input")
    _cache_bundle(
        tmp_path,
        bundle("example-edition", ("eclab", "example-edition")),
        "same-input",
    )

    assert cached_bundle_fingerprint(tmp_path, "same-input", pipeline_id="eclab") == fingerprint
    assert (
        cached_bundle_fingerprint(tmp_path, "same-input", pipeline_id="example-edition")
        == fingerprint
    )
    assert (tmp_path / "pipelines" / "eclab" / "latest.json").is_file()
    assert (tmp_path / "pipelines" / "example-edition" / "latest.json").is_file()

    (tmp_path / "latest.json").write_text(
        json.dumps(
            {
                "cache_format": 2,
                "fingerprint": fingerprint,
                "input_fingerprint": "legacy-only",
                "pipeline_id": "eclab",
            }
        )
    )
    assert cached_bundle_fingerprint(tmp_path, "legacy-only", pipeline_id="eclab") is None
    loaded = load_cached_bundle(tmp_path, fingerprint, pipeline_id="example-edition")
    assert loaded.pipeline_lineage == ("eclab", "example-edition")
