from engulf_api import ApplicationMetadata
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    CompletionContext,
    CompletionRegistry,
    Shell,
    invoke_provider,
    normalize_candidate,
)

from engulf_clab_schema_api import (
    ExplainedValue,
    PluginSchema,
    ValueType,
    register_schema_arguments,
    register_schema_completions,
)

APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="ECLAB",
    vendor="Engulf",
    product="ECLAB",
    short_product_name="eclab",
    version="1.0",
)


def _context(*words: str, cursor: int | None = None) -> CompletionContext:
    return CompletionContext(
        Shell.BASH,
        "eclab",
        "containerlab",
        tuple(words),
        len(words) - 1 if cursor is None else cursor,
    )


def test_schema_registers_global_environment_option_and_values() -> None:
    schema = (
        PluginSchema("example.plugin", package="example")
        .add_runtime_var("EXAMPLE_MODE", "Legacy mode.", values=ValueType.STRING)
        .add_cli_flag(
            "--example-mode",
            "Select the mode.",
            values=(
                ExplainedValue("safe", "Use safe behavior."),
                ExplainedValue("fast", "Use fast behavior."),
            ),
            environment="EXAMPLE_MODE",
        )
        .annotate("--example-mode", commands=("deploy",))
    )
    registry = ArgumentRegistry()

    register_schema_arguments(registry, schema, APPLICATION)

    option = registry.find_exact("--example-mode")
    assert option is not None
    assert option.environment == "EXAMPLE_MODE"
    assert option.when is not None
    assert option.when(_context("deploy", "--example-mode"))
    assert not option.when(_context("destroy", "--example-mode"))
    assert option.value_completer is not None
    candidates = [
        normalize_candidate(item) for item in invoke_provider(option.value_completer, _context("s"))
    ]
    assert [(item.value, item.description) for item in candidates] == [
        ("safe", "Use safe behavior.")
    ]


def test_schema_completes_file_paths(tmp_path) -> None:
    target = tmp_path / "source.qcow2"
    target.write_text("", encoding="utf-8")
    schema = PluginSchema("example.plugin", package="example").add_cli_flag(
        "--example-source",
        "Select a source.",
        values=ValueType.FILE_PATH,
    )
    registry = ArgumentRegistry()
    register_schema_arguments(registry, schema, APPLICATION)
    option = registry.find_exact("--example-source")
    assert option is not None
    assert option.value_completer is not None

    candidates = [
        normalize_candidate(item).value
        for item in invoke_provider(
            option.value_completer,
            _context(f"{tmp_path}/sou"),
        )
    ]

    assert candidates == [str(target)]


def test_schema_completes_edition_command_scoped_flags_and_arguments() -> None:
    schema = (
        PluginSchema("example.plugin", package="example")
        .add_command("install-{short_product}", "Install runtime data.")
        .add_cli_argument(
            "install-{short_product}",
            "ROOT",
            "Select the root.",
            values=("root-a", "root-b"),
        )
        .add_cli_flag(
            "--global-value",
            "Set a wrapper-global value.",
            values=ValueType.STRING,
        )
        .add_cli_flag(
            "--force",
            "Replace an existing installation.",
            command="install-{short_product}",
        )
    )
    registry = CompletionRegistry()
    register_schema_completions(registry, schema, APPLICATION)
    provider = registry.providers[0]

    commands = [
        normalize_candidate(item).value for item in invoke_provider(provider, _context("install-"))
    ]
    flags = [
        normalize_candidate(item).value
        for item in invoke_provider(provider, _context("install-eclab", "--"))
    ]
    after_global = [
        normalize_candidate(item).value
        for item in invoke_provider(
            provider,
            _context("install-eclab", "--global-value", "value", ""),
        )
    ]

    assert commands == ["install-eclab"]
    assert flags == ["--force"]
    assert after_global == ["root-a", "root-b", "--force"]
