from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from engulf_api import ApplicationMetadata, RegistrationAPI
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    CompletionCandidate,
    CompletionContext,
    CompletionRegistry,
    ExecutableWrapperPlugin,
    Runtime,
)

from .builder import PluginSchema
from .models import JsonScalar, OptionDeclaration, OptionKind, ValueMode, ValueType

_PATH_TYPES = frozenset({ValueType.FILE_PATH.value, ValueType.DIRECTORY_PATH.value})


class SchemaBackedPlugin(ExecutableWrapperPlugin):
    """Executable-wrapper plugin whose completion metadata comes from one schema."""

    schema: ClassVar[PluginSchema]

    def register_arguments(
        self,
        registry: ArgumentRegistry,
        api: RegistrationAPI,
    ) -> None:
        register_schema_arguments(registry, self.schema, api.application)

    def register_completions(
        self,
        registry: CompletionRegistry,
        api: RegistrationAPI,
    ) -> None:
        register_schema_completions(registry, self.schema, api.application)


def register_schema_arguments(
    registry: ArgumentRegistry,
    schema: PluginSchema,
    application: ApplicationMetadata,
) -> None:
    """Register global schema flags for hiding, value, and environment handling."""
    command_scopes = {
        annotation.subject: annotation.commands
        for annotation in schema.annotations(application)
        if annotation.commands
    }
    for option in schema.options(application):
        if option.kind is not OptionKind.CLI_FLAG or option.command is not None:
            continue
        registry.option(
            option.name,
            *option.aliases,
            takes_value=option.value_mode is not None,
            metavar=_metavar(option),
            description=_description(option),
            value_completer=(
                None
                if option.value_mode is None
                else Runtime(
                    f"schema-value:{option.name}",
                    _ValueCompleter(option),
                )
            ),
            repeatable=option.repeatable,
            when=(
                _CommandPredicate(command_scopes[option.name])
                if option.name in command_scopes
                else None
            ),
            environment=option.environment,
        )


def register_schema_completions(
    registry: CompletionRegistry,
    schema: PluginSchema,
    application: ApplicationMetadata,
) -> None:
    """Register commands, scoped flags, and positional values from a schema."""
    options = schema.options(application)
    if any(option.kind is OptionKind.COMMAND for option in options):
        registry.provider(Runtime("schema-commands", _CommandCompleter(options)))


class _ValueCompleter:
    def __init__(self, option: OptionDeclaration) -> None:
        self._option = option

    def complete(self, context: CompletionContext) -> Iterable[CompletionCandidate]:
        return _value_candidates(self._option, context.current)


class _CommandCompleter:
    def __init__(self, options: tuple[OptionDeclaration, ...]) -> None:
        self._commands = tuple(option for option in options if option.kind is OptionKind.COMMAND)
        self._flags = tuple(
            option
            for option in options
            if option.kind is OptionKind.CLI_FLAG and option.command is not None
        )
        self._global_flags = tuple(
            option
            for option in options
            if option.kind is OptionKind.CLI_FLAG and option.command is None
        )
        self._arguments = tuple(
            option for option in options if option.kind is OptionKind.CLI_ARGUMENT
        )

    def complete(self, context: CompletionContext) -> Iterable[CompletionCandidate]:
        if context.cursor_index == 0:
            return self._command_candidates(context.current)
        if not context.words:
            return ()
        command = self._canonical_command(context.words[0])
        if command is None:
            return ()
        flags = tuple(option for option in self._flags if option.command == command)
        assignment = _assignment(flags, context.current)
        if assignment is not None:
            option, name, value = assignment
            return tuple(
                CompletionCandidate(f"{name}={item.value}", item.description)
                for item in _value_candidates(option, value)
            )
        previous = next(
            (
                option
                for option in flags
                if context.previous in (option.name, *option.aliases)
                and option.value_mode is not None
            ),
            None,
        )
        if previous is not None:
            return _value_candidates(previous, context.current)
        if context.current.startswith("-"):
            return _flag_candidates(flags, context)
        positional = self._positional_option(
            command,
            (*self._global_flags, *flags),
            context,
        )
        values = () if positional is None else _value_candidates(positional, context.current)
        return (*values, *_flag_candidates(flags, context))

    def _command_candidates(self, current: str) -> tuple[CompletionCandidate, ...]:
        result: list[CompletionCandidate] = []
        for command in self._commands:
            for name in (command.name, *command.aliases):
                if name.startswith(current):
                    result.append(CompletionCandidate(name, _description(command)))
        return tuple(result)

    def _canonical_command(self, value: str) -> str | None:
        for command in self._commands:
            if value in (command.name, *command.aliases):
                return command.name
        return None

    def _positional_option(
        self,
        command: str,
        flags: tuple[OptionDeclaration, ...],
        context: CompletionContext,
    ) -> OptionDeclaration | None:
        positional = tuple(option for option in self._arguments if option.command == command)
        consumed = _positional_count(flags, context.words[1 : context.cursor_index])
        if not positional:
            return None
        if consumed < len(positional):
            return positional[consumed]
        final = positional[-1]
        return final if final.repeatable else None


class _CommandPredicate:
    def __init__(self, commands: tuple[str, ...]) -> None:
        self._commands = frozenset(commands)

    def __call__(self, context: CompletionContext) -> bool:
        if context.cursor_index == 0:
            return True
        return any(word in self._commands for word in context.words[: context.cursor_index])


def _assignment(
    options: tuple[OptionDeclaration, ...], current: str
) -> tuple[OptionDeclaration, str, str] | None:
    if "=" not in current:
        return None
    name, value = current.split("=", 1)
    for option in options:
        if option.value_mode is not None and name in (option.name, *option.aliases):
            return option, name, value
    return None


def _flag_candidates(
    options: tuple[OptionDeclaration, ...], context: CompletionContext
) -> tuple[CompletionCandidate, ...]:
    prior = context.words[: context.cursor_index]
    result: list[CompletionCandidate] = []
    for option in options:
        names = (option.name, *option.aliases)
        if not option.repeatable and any(
            word in names or word.partition("=")[0] in names for word in prior
        ):
            continue
        for name in names:
            if name.startswith(context.current):
                suffix = "=" if option.value_mode is not None and name.startswith("--") else ""
                result.append(CompletionCandidate(name + suffix, _description(option)))
    return tuple(result)


def _positional_count(flags: tuple[OptionDeclaration, ...], words: tuple[str, ...]) -> int:
    names = {name: option for option in flags for name in (option.name, *option.aliases)}
    count = 0
    index = 0
    while index < len(words):
        word = words[index]
        if word == "--":
            count += len(words) - index - 1
            break
        name = word.partition("=")[0]
        option = names.get(name)
        if option is None:
            count += 1
            index += 1
        elif option.value_mode is not None and "=" not in word:
            index += 2
        else:
            index += 1
    return count


def _value_candidates(option: OptionDeclaration, current: str) -> tuple[CompletionCandidate, ...]:
    result: list[CompletionCandidate] = []
    descriptions = {_literal(item.value): item.explanation for item in option.explained_values}
    if option.value_mode is ValueMode.LITERAL:
        for value in option.values:
            rendered = _literal(value)
            if rendered.startswith(current):
                result.append(CompletionCandidate(rendered, descriptions.get(rendered)))
    elif option.value_mode is ValueMode.TYPE:
        if ValueType.BOOLEAN.value in option.values:
            result.extend(
                CompletionCandidate(value)
                for value in ("true", "false")
                if value.startswith(current)
            )
        if _PATH_TYPES.intersection(option.values):
            result.extend(
                _path_candidates(
                    current,
                    directories_only=(
                        ValueType.DIRECTORY_PATH.value in option.values
                        and ValueType.FILE_PATH.value not in option.values
                    ),
                )
            )
        for explained in option.explained_values:
            rendered = _literal(explained.value)
            if rendered.startswith(current):
                result.append(CompletionCandidate(rendered, explained.explanation))
    if option.has_default:
        default = json.loads(option.default_json or "null")
        if default is None or isinstance(default, str | int | float | bool):
            rendered = _literal(default)
            if rendered.startswith(current):
                result.append(CompletionCandidate(rendered, "Default value"))
    deduplicated: dict[str, CompletionCandidate] = {}
    for candidate in result:
        existing = deduplicated.get(candidate.value)
        if existing is None or (existing.description is None and candidate.description is not None):
            deduplicated[candidate.value] = candidate
    return tuple(deduplicated.values())


def _path_candidates(current: str, *, directories_only: bool) -> list[CompletionCandidate]:
    separator = current.rfind("/")
    shown_parent = current[: separator + 1] if separator >= 0 else ""
    prefix = current[separator + 1 :]
    try:
        directory = Path(shown_parent or ".").expanduser()
    except RuntimeError:
        return []
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError:
        return []
    result: list[CompletionCandidate] = []
    for entry in entries:
        if not entry.name.startswith(prefix) or (directories_only and not entry.is_dir()):
            continue
        value = f"{shown_parent}{entry.name}"
        if entry.is_dir():
            value += "/"
        result.append(CompletionCandidate(value))
    return result


def _literal(value: JsonScalar | str) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, allow_nan=False)


def _description(option: OptionDeclaration) -> str:
    if not option.deprecated:
        return option.explanation
    replacement = "" if option.replacement is None else f"; use {option.replacement}"
    return f"{option.explanation} (deprecated{replacement})"


def _metavar(option: OptionDeclaration) -> str | None:
    if option.value_mode is None:
        return None
    if option.value_mode is ValueMode.LITERAL:
        return "VALUE"
    if len(option.values) == 1:
        return str(option.values[0]).replace("-", "_").upper()
    return "VALUE"
