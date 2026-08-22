from pathlib import Path

import pytest
from engulf_api import ApplicationMetadata

from engulf_clab_schema_api import (
    ExplainedValue,
    LifecycleStage,
    PathBase,
    PluginSchema,
    Privilege,
    ValueMode,
    ValueType,
)

APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="ECLAB",
    vendor="Engulf",
    product="ECLAB",
    short_product_name="eclab",
    version="1.0",
)


def test_builder_expands_commands_and_snapshots_packaged_reference() -> None:
    schema = (
        PluginSchema("engulf_clab.schema", package="engulf_clab_schema")
        .add_command("install-{short_product}", "Install the generated data.")
        .add_cli_argument(
            "install-{short_product}",
            "ROOT",
            "Select the configuration root.",
            values=ValueType.DIRECTORY_PATH,
        )
        .add_cli_flag(
            "--force", "Replace a recognized generation.", command="install-{short_product}"
        )
        .add_runtime_var(
            "ECLAB_JOBS", "Limit workers.", values=ValueType.POSITIVE_INTEGER, default=2
        )
        .add_node_prop("labels.ECLAB_*", "Declare an ECLAB node label.", values=ValueType.STRING)
        .add_node_var("ECLAB_VAR_*", "Declare an ECLAB node variable.", values=ValueType.STRING)
        .annotate(
            "ROOT",
            commands=("install-{short_product}",),
            lifecycle=(LifecycleStage.BEFORE_GOAL,),
            requires=("The directory already exists.",),
            path_base=PathBase.INVOCATION_DIRECTORY,
            examples=("~/.codex",),
        )
        .require_host_tool("git", "Resolve the selected source revision.")
        .require_privilege(Privilege.NONE, "No elevated privilege is required.")
        .order(
            LifecycleStage.BEFORE_GOAL,
            "Record before the terminal generator.",
            before=("engulf_clab.generator",),
        )
        .route("install-runtime-data", "README.md", "Read installation behavior.")
        .use_case("Generate exact runtime documentation.")
        .reject("Do not substitute controls from an inactive plugin.")
        .refer("README.md")
    )

    snapshot = schema.snapshot(APPLICATION)

    assert snapshot.options[0].name == "install-eclab"
    assert snapshot.options[1].command == "install-eclab"
    assert snapshot.references[0].path == "README.md"
    assert snapshot.references[0].content.startswith(b"# engulf-clab runtime schema")
    assert snapshot.annotations[0].commands == ("install-eclab",)
    assert snapshot.annotations[0].path_base is PathBase.INVOCATION_DIRECTORY
    assert snapshot.requirements[0].name == "git"
    assert snapshot.ordering[0].before == ("engulf_clab.generator",)
    assert snapshot.routes[0].task == "install-runtime-data"


@pytest.mark.parametrize("explanation", ["", "two\nlines", "x" * 241])
def test_explanations_are_short_single_lines(explanation: str) -> None:
    with pytest.raises(ValueError):
        PluginSchema("example.plugin", package="example").add_command("run", explanation)


def test_values_accept_explained_literals_alongside_an_open_type() -> None:
    schema = PluginSchema("example.plugin", package="example").add_node_prop(
        "image",
        "Select an image.",
        values=(
            ValueType.IMAGE_REFERENCE,
            ExplainedValue("example/helper", "Use the packaged helper node."),
        ),
    )

    option = schema._options[0]
    assert option.value_mode is ValueMode.TYPE
    assert option.values == (ValueType.IMAGE_REFERENCE.value,)
    assert option.explained_values == (
        ExplainedValue("example/helper", "Use the packaged helper node."),
    )


@pytest.mark.parametrize("explanation", ["", "two\nlines", "x" * 241])
def test_explained_value_explanations_are_short_single_lines(explanation: str) -> None:
    with pytest.raises(ValueError):
        PluginSchema("example.plugin", package="example").add_node_prop(
            "image",
            "Select an image.",
            values=(ExplainedValue("example/helper", explanation),),
        )


def test_command_scope_and_duplicates_are_validated() -> None:
    schema = PluginSchema("example.plugin", package="example")
    with pytest.raises(ValueError, match="declared first"):
        schema.add_cli_flag("--bad", "Invalid scope.", command="missing")
    schema.add_command("run", "Run it.")
    schema.add_cli_flag("--flag", "Enable it.", command="run")
    with pytest.raises(ValueError, match="collide"):
        schema.add_cli_flag("--flag", "Enable it again.", command="run")
    with pytest.raises(ValueError, match="collide"):
        schema.add_cli_flag(("-f", "--flag"), "Collide through an alias.", command="run")


def test_environment_names_are_validated() -> None:
    with pytest.raises(ValueError, match="shell-style"):
        PluginSchema("example.plugin", package="example").add_node_var(
            "not.valid", "Invalid environment name.", values=ValueType.STRING
        )


def test_references_refuse_traversal() -> None:
    with pytest.raises(ValueError, match="traversal"):
        PluginSchema("example.plugin", package="example").refer(Path("../README.md"))


def test_semantics_require_declared_options_and_packaged_routes() -> None:
    schema = PluginSchema("engulf_clab.schema", package="engulf_clab_schema")
    with pytest.raises(ValueError, match="declared option"):
        schema.annotate("MISSING", requires=("something",))
    schema.add_runtime_var("KNOWN", "A known value.", values=ValueType.STRING)
    schema.route("missing-reference", "missing.md", "Read missing details.").refer("README.md")
    with pytest.raises(ValueError, match="unpackaged"):
        schema.snapshot(APPLICATION)
