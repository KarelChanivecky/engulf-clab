from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.resources
import json
import math
import re
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Self, cast

from engulf_api import ApplicationMetadata

from .models import (
    UNSET,
    ExplainedValue,
    JsonScalar,
    JsonValue,
    LifecycleStage,
    NodeKindDeclaration,
    OptionDeclaration,
    OptionKind,
    PathBase,
    PluginOrdering,
    Privilege,
    RecordedPluginSchema,
    ReferenceSnapshot,
    RequirementKind,
    RuntimeRequirement,
    SchemaScope,
    SemanticAnnotation,
    TaskRoute,
    UnsetType,
    ValueMode,
    ValueSpec,
    ValueType,
)

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_COMMAND = re.compile(r"^[a-z0-9][a-z0-9_.{}-]*$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\*)?$")
_TASK = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TOOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")
_NODE_KIND = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_REFERENCE_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})
_MAX_REFERENCE_BYTES = 1024 * 1024
_MAX_PROVIDER_BYTES = 8 * 1024 * 1024


def _prose(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{label} must not be empty")
    if len(result) > 240:
        raise ValueError(f"{label} must contain at most 240 characters")
    if any(character in "\r\n" or ord(character) < 32 for character in result):
        raise ValueError(f"{label} must be one line without control characters")
    return result


def _freeze_default(value: JsonValue | UnsetType) -> tuple[bool, str | None]:
    if isinstance(value, UnsetType):
        return False, None
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("default must be a finite JSON value") from error
    return True, encoded


def _normalize_values(
    values: ValueSpec,
) -> tuple[ValueMode, tuple[JsonScalar | str, ...], tuple[ExplainedValue, ...]]:
    if isinstance(values, ValueType):
        return ValueMode.TYPE, (values.value,), ()
    if type(values) is not tuple or not values:
        raise ValueError("values must be a ValueType or a nonempty tuple")
    plain_values = tuple(item for item in values if not isinstance(item, ExplainedValue))
    explained_values = tuple(item for item in values if isinstance(item, ExplainedValue))
    normalized_explained: list[ExplainedValue] = []
    for item in explained_values:
        _validate_literal(item.value)
        normalized_explained.append(
            ExplainedValue(item.value, _prose(item.explanation, label="value explanation"))
        )
    if plain_values and all(isinstance(item, ValueType) for item in plain_values):
        typed_values = cast(tuple[ValueType, ...], plain_values)
        normalized = tuple(item.value for item in typed_values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("values must not contain duplicates")
        _reject_duplicate_explained(normalized_explained)
        return ValueMode.TYPE, normalized, tuple(normalized_explained)
    if any(isinstance(item, ValueType) for item in plain_values):
        raise TypeError("literal values and ValueType members cannot be mixed")
    normalized_literals: list[JsonScalar] = []
    encoded_seen: set[str] = set()
    for literal in plain_values:
        _validate_literal(literal)
        encoded = json.dumps(literal, sort_keys=True, allow_nan=False)
        if encoded in encoded_seen:
            raise ValueError("values must not contain duplicates")
        encoded_seen.add(encoded)
        normalized_literals.append(literal)
    for explained in normalized_explained:
        encoded = json.dumps(explained.value, sort_keys=True, allow_nan=False)
        if encoded in encoded_seen:
            raise ValueError("values must not contain duplicates")
        encoded_seen.add(encoded)
        normalized_literals.append(explained.value)
    return ValueMode.LITERAL, tuple(normalized_literals), tuple(normalized_explained)


def _validate_literal(item: object) -> None:
    if item is not None and type(item) not in {str, int, float, bool}:
        raise TypeError("literal values must be JSON scalars")
    if isinstance(item, float) and not math.isfinite(item):
        raise ValueError("literal float values must be finite")


def _reject_duplicate_explained(values: list[ExplainedValue]) -> None:
    encoded = [json.dumps(item.value, sort_keys=True, allow_nan=False) for item in values]
    if len(set(encoded)) != len(encoded):
        raise ValueError("values must not contain duplicates")


def _validate_pattern(value: str, *, label: str, dotted: bool) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    if value.count("*") > 1:
        raise ValueError(f"{label} may contain at most one wildcard")
    if "*" in value:
        final = _split_path(value)[-1] if dotted else value
        if "*" not in final:
            raise ValueError(f"{label} wildcard must be in the final segment")
    return value


def _split_path(path: str) -> tuple[str, ...]:
    segments: list[str] = []
    current: list[str] = []
    escaped = False
    for character in path:
        if escaped:
            if character not in {".", "\\"}:
                raise ValueError("path escapes may contain only a dot or backslash")
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ".":
            if not current:
                raise ValueError("property path segments must not be empty")
            segments.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped or not current:
        raise ValueError("property path has an incomplete escape or empty segment")
    segments.append("".join(current))
    return tuple(segments)


def split_property_path(path: str) -> tuple[str, ...]:
    _validate_pattern(path, label="property path", dotted=True)
    return _split_path(path)


def _expand(value: str, short_product: str) -> str:
    if "{" in value or "}" in value:
        if value.count("{short_product}") != 1:
            raise ValueError("only one {short_product} placeholder is supported")
        value = value.replace("{short_product}", short_product)
        if "{" in value or "}" in value:
            raise ValueError("unsupported application placeholder")
    return value


def normalized_short_product(application: ApplicationMetadata) -> str:
    source = application.short_product_name or application.product
    normalized = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
    if not normalized:
        raise ValueError("application short product name cannot be normalized")
    return normalized


class PluginSchema:
    def __init__(self, plugin_id: str, *, package: str) -> None:
        if not isinstance(plugin_id, str) or _PLUGIN_ID.fullmatch(plugin_id) is None:
            raise ValueError("plugin_id must be a lowercase dot-qualified identifier")
        if not isinstance(package, str) or not package:
            raise ValueError("package must be a nonempty import package name")
        self.plugin_id = plugin_id
        self.package = package
        self._options: list[OptionDeclaration] = []
        self._use_cases: list[str] = []
        self._rejections: list[str] = []
        self._references: list[tuple[str, str | None]] = []
        self._annotations: list[SemanticAnnotation] = []
        self._requirements: list[RuntimeRequirement] = []
        self._routes: list[TaskRoute] = []
        self._ordering: list[PluginOrdering] = []
        self._node_kinds: list[NodeKindDeclaration] = []
        self._keys: set[tuple[object, ...]] = set()

    def _add(self, option: OptionDeclaration, key: tuple[object, ...]) -> Self:
        if key in self._keys:
            raise ValueError(f"duplicate schema declaration for {option.name}")
        self._keys.add(key)
        self._options.append(option)
        return self

    def add_command(
        self,
        name: str,
        explanation: str,
        *,
        aliases: tuple[str, ...] = (),
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        if _COMMAND.fullmatch(name) is None:
            raise ValueError("command must be one token")
        if type(aliases) is not tuple or any(_COMMAND.fullmatch(item) is None for item in aliases):
            raise ValueError("command aliases must be a tuple of command tokens")
        self._validate_status(deprecated, replacement)
        return self._add(
            OptionDeclaration(
                OptionKind.COMMAND,
                name,
                _prose(explanation, label="explanation"),
                aliases=aliases,
                deprecated=deprecated,
                replacement=replacement,
            ),
            (OptionKind.COMMAND, name),
        )

    def add_cli_argument(
        self,
        command: str,
        name: str,
        explanation: str,
        *,
        values: ValueSpec,
        required: bool = True,
        repeatable: bool = False,
        default: JsonValue | UnsetType = UNSET,
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        self._require_command(command)
        if not isinstance(name, str) or not name or any(character.isspace() for character in name):
            raise ValueError("CLI argument name must be one nonempty token")
        return self._value_option(
            OptionKind.CLI_ARGUMENT,
            name,
            explanation,
            values=values,
            command=command,
            required=required,
            repeatable=repeatable,
            default=default,
            deprecated=deprecated,
            replacement=replacement,
            key=(OptionKind.CLI_ARGUMENT, command, name),
        )

    def add_cli_flag(
        self,
        names: str | tuple[str, ...],
        explanation: str,
        *,
        command: str | None = None,
        values: ValueSpec | None = None,
        required: bool = False,
        repeatable: bool = False,
        default: JsonValue | UnsetType = UNSET,
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        normalized_names = (names,) if isinstance(names, str) else names
        if type(normalized_names) is not tuple or not normalized_names:
            raise ValueError("CLI flag names must be a nonempty tuple")
        if any(
            not isinstance(item, str)
            or not item.startswith("-")
            or any(character.isspace() for character in item)
            for item in normalized_names
        ):
            raise ValueError("CLI flag names must be single tokens starting with a hyphen")
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("CLI flag aliases must be unique")
        if command is not None:
            self._require_command(command)
        requested_names = set(normalized_names)
        for option in self._options:
            if option.kind is not OptionKind.CLI_FLAG or option.command != command:
                continue
            if requested_names.intersection((option.name, *option.aliases)):
                raise ValueError("CLI flag names collide with an existing declaration")
        self._validate_status(deprecated, replacement)
        has_default, default_json = _freeze_default(default)
        if values is None:
            if has_default and default_json not in {"true", "false"}:
                raise ValueError("a switch default must be boolean")
            mode = None
            normalized_values: tuple[JsonScalar | str, ...] = ()
            explained_values: tuple[ExplainedValue, ...] = ()
        else:
            mode, normalized_values, explained_values = _normalize_values(values)
        return self._add(
            OptionDeclaration(
                OptionKind.CLI_FLAG,
                normalized_names[0],
                _prose(explanation, label="explanation"),
                aliases=normalized_names[1:],
                command=command,
                value_mode=mode,
                values=normalized_values,
                explained_values=explained_values,
                required=required,
                repeatable=repeatable,
                has_default=has_default,
                default_json=default_json,
                deprecated=deprecated,
                replacement=replacement,
            ),
            (OptionKind.CLI_FLAG, command, *normalized_names),
        )

    def add_runtime_var(
        self,
        name: str,
        explanation: str,
        *,
        values: ValueSpec,
        default: JsonValue | UnsetType = UNSET,
        required: bool = False,
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        _validate_pattern(name, label="runtime variable", dotted=False)
        if _ENV_NAME.fullmatch(name) is None:
            raise ValueError("runtime variable must be a shell-style name or final wildcard")
        return self._value_option(
            OptionKind.RUNTIME_VAR,
            name,
            explanation,
            values=values,
            required=required,
            default=default,
            deprecated=deprecated,
            replacement=replacement,
            key=(OptionKind.RUNTIME_VAR, name),
        )

    def add_root_prop(
        self,
        path: str,
        explanation: str,
        *,
        values: ValueSpec,
        default: JsonValue | UnsetType = UNSET,
        required: bool = False,
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        return self._property(
            SchemaScope.ROOT,
            path,
            explanation,
            values=values,
            default=default,
            required=required,
            deprecated=deprecated,
            replacement=replacement,
        )

    def add_node_prop(
        self,
        path: str,
        explanation: str,
        *,
        values: ValueSpec,
        default: JsonValue | UnsetType = UNSET,
        required: bool = False,
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        return self._property(
            SchemaScope.NODE,
            path,
            explanation,
            values=values,
            default=default,
            required=required,
            deprecated=deprecated,
            replacement=replacement,
        )

    def add_link_prop(
        self,
        path: str,
        explanation: str,
        *,
        values: ValueSpec,
        default: JsonValue | UnsetType = UNSET,
        required: bool = False,
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        return self._property(
            SchemaScope.LINK,
            path,
            explanation,
            values=values,
            default=default,
            required=required,
            deprecated=deprecated,
            replacement=replacement,
        )

    def add_node_var(
        self,
        name: str,
        explanation: str,
        *,
        values: ValueSpec,
        default: JsonValue | UnsetType = UNSET,
        required: bool = False,
        deprecated: bool = False,
        replacement: str | None = None,
    ) -> Self:
        _validate_pattern(name, label="node variable", dotted=False)
        if _ENV_NAME.fullmatch(name) is None:
            raise ValueError("node variable must be a shell-style name or final wildcard")
        return self._value_option(
            OptionKind.NODE_VAR,
            name,
            explanation,
            values=values,
            scope=SchemaScope.NODE,
            required=required,
            default=default,
            deprecated=deprecated,
            replacement=replacement,
            key=(OptionKind.NODE_VAR, name),
        )

    def _property(
        self,
        scope: SchemaScope,
        path: str,
        explanation: str,
        *,
        values: ValueSpec,
        default: JsonValue | UnsetType,
        required: bool,
        deprecated: bool,
        replacement: str | None,
    ) -> Self:
        segments = split_property_path(path)
        return self._value_option(
            OptionKind.PROPERTY,
            path,
            explanation,
            values=values,
            scope=scope,
            default=default,
            required=required,
            deprecated=deprecated,
            replacement=replacement,
            key=(OptionKind.PROPERTY, scope, segments),
        )

    def _value_option(
        self,
        kind: OptionKind,
        name: str,
        explanation: str,
        *,
        values: ValueSpec,
        command: str | None = None,
        scope: SchemaScope | None = None,
        required: bool = False,
        repeatable: bool = False,
        default: JsonValue | UnsetType = UNSET,
        deprecated: bool = False,
        replacement: str | None = None,
        key: tuple[object, ...],
    ) -> Self:
        mode, normalized_values, explained_values = _normalize_values(values)
        self._validate_status(deprecated, replacement)
        has_default, default_json = _freeze_default(default)
        return self._add(
            OptionDeclaration(
                kind,
                name,
                _prose(explanation, label="explanation"),
                command=command,
                scope=scope,
                value_mode=mode,
                values=normalized_values,
                explained_values=explained_values,
                required=required,
                repeatable=repeatable,
                has_default=has_default,
                default_json=default_json,
                deprecated=deprecated,
                replacement=replacement,
            ),
            key,
        )

    def use_case(self, explanation: str) -> Self:
        normalized = _prose(explanation, label="use case")
        if normalized in self._use_cases:
            raise ValueError("duplicate use case")
        self._use_cases.append(normalized)
        return self

    def reject(self, reason: str) -> Self:
        normalized = _prose(reason, label="rejection reason")
        if normalized in self._rejections:
            raise ValueError("duplicate rejection reason")
        self._rejections.append(normalized)
        return self

    def annotate(
        self,
        subject: str,
        *,
        commands: tuple[str, ...] = (),
        lifecycle: tuple[LifecycleStage, ...] = (),
        requires: tuple[str, ...] = (),
        conflicts_with: tuple[str, ...] = (),
        implies: tuple[str, ...] = (),
        path_base: PathBase | None = None,
        privilege: Privilege | None = None,
        host_tools: tuple[str, ...] = (),
        shared_with: tuple[str, ...] = (),
        examples: tuple[str, ...] = (),
    ) -> Self:
        if not any(option.name == subject or subject in option.aliases for option in self._options):
            raise ValueError(f"semantic subject must name a declared option: {subject}")
        if any(item.subject == subject for item in self._annotations):
            raise ValueError(f"duplicate semantic annotation for {subject}")
        normalized_commands = _tokens(commands, label="commands", pattern=_COMMAND)
        if type(lifecycle) is not tuple or any(
            not isinstance(item, LifecycleStage) for item in lifecycle
        ):
            raise TypeError("lifecycle must be a tuple of LifecycleStage members")
        if len(set(lifecycle)) != len(lifecycle):
            raise ValueError("lifecycle must not contain duplicates")
        normalized_requires = _prose_tuple(requires, label="requires")
        normalized_conflicts = _prose_tuple(conflicts_with, label="conflicts_with")
        normalized_implies = _prose_tuple(implies, label="implies")
        normalized_tools = _tokens(host_tools, label="host_tools", pattern=_TOOL)
        normalized_shared = _tokens(shared_with, label="shared_with", pattern=_PLUGIN_ID)
        normalized_examples = _prose_tuple(examples, label="examples")
        if path_base is not None and not isinstance(path_base, PathBase):
            raise TypeError("path_base must be a PathBase or None")
        if privilege is not None and not isinstance(privilege, Privilege):
            raise TypeError("privilege must be a Privilege or None")
        if not any(
            (
                normalized_commands,
                lifecycle,
                normalized_requires,
                normalized_conflicts,
                normalized_implies,
                path_base,
                privilege,
                normalized_tools,
                normalized_shared,
                normalized_examples,
            )
        ):
            raise ValueError("semantic annotation must provide at least one detail")
        self._annotations.append(
            SemanticAnnotation(
                subject,
                normalized_commands,
                lifecycle,
                normalized_requires,
                normalized_conflicts,
                normalized_implies,
                path_base,
                privilege,
                normalized_tools,
                normalized_shared,
                normalized_examples,
            )
        )
        return self

    def require_host_tool(
        self,
        name: str,
        explanation: str,
        *,
        commands: tuple[str, ...] = (),
    ) -> Self:
        if _TOOL.fullmatch(name) is None:
            raise ValueError("host tool must be one executable-style token")
        return self._requirement(
            RequirementKind.HOST_TOOL,
            name,
            explanation,
            commands=commands,
        )

    def require_privilege(
        self,
        privilege: Privilege,
        explanation: str,
        *,
        commands: tuple[str, ...] = (),
    ) -> Self:
        if not isinstance(privilege, Privilege):
            raise TypeError("privilege must be a Privilege member")
        return self._requirement(
            RequirementKind.PRIVILEGE,
            privilege.value,
            explanation,
            commands=commands,
        )

    def _requirement(
        self,
        kind: RequirementKind,
        name: str,
        explanation: str,
        *,
        commands: tuple[str, ...],
    ) -> Self:
        normalized_commands = _tokens(commands, label="commands", pattern=_COMMAND)
        key = (kind, name, normalized_commands)
        if any((item.kind, item.name, item.commands) == key for item in self._requirements):
            raise ValueError(f"duplicate runtime requirement: {name}")
        self._requirements.append(
            RuntimeRequirement(
                kind,
                name,
                _prose(explanation, label="requirement explanation"),
                normalized_commands,
            )
        )
        return self

    def route(self, task: str, reference: str, explanation: str) -> Self:
        if _TASK.fullmatch(task) is None:
            raise ValueError("task must be a lowercase kebab-case token")
        candidate = PurePosixPath(reference)
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ValueError("route reference must be package-relative without traversal")
        route = TaskRoute(
            task, candidate.as_posix(), _prose(explanation, label="route explanation")
        )
        if any(item.task == task and item.reference == route.reference for item in self._routes):
            raise ValueError(f"duplicate task route: {task} -> {route.reference}")
        self._routes.append(route)
        return self

    def order(
        self,
        stage: LifecycleStage,
        explanation: str,
        *,
        after: tuple[str, ...] = (),
        before: tuple[str, ...] = (),
    ) -> Self:
        if not isinstance(stage, LifecycleStage):
            raise TypeError("stage must be a LifecycleStage member")
        normalized_after = _tokens(after, label="after", pattern=_PLUGIN_ID)
        normalized_before = _tokens(before, label="before", pattern=_PLUGIN_ID)
        if not normalized_after and not normalized_before:
            raise ValueError("ordering must declare at least one before or after plugin")
        if set(normalized_after).intersection(normalized_before):
            raise ValueError("a plugin cannot appear in both after and before")
        item = PluginOrdering(
            stage,
            _prose(explanation, label="ordering explanation"),
            normalized_after,
            normalized_before,
        )
        if item in self._ordering:
            raise ValueError("duplicate plugin ordering declaration")
        self._ordering.append(item)
        return self

    def add_node_kind(
        self,
        kind: str,
        explanation: str,
        *,
        reference: str,
    ) -> Self:
        if not isinstance(kind, str) or _NODE_KIND.fullmatch(kind) is None:
            raise ValueError("node kind must be an exact lowercase Containerlab kind value")
        candidate = PurePosixPath(reference)
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ValueError("node kind reference must be package-relative without traversal")
        if candidate.suffix.lower() not in _REFERENCE_SUFFIXES:
            raise ValueError("unsupported node kind reference file type")
        if any(item.kind == kind for item in self._node_kinds):
            raise ValueError(f"duplicate node kind declaration: {kind}")
        self._node_kinds.append(
            NodeKindDeclaration(
                kind,
                _prose(explanation, label="node kind explanation"),
                candidate.as_posix(),
            )
        )
        return self

    def refer(self, path: str | PurePosixPath, *, title: str | None = None) -> Self:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ValueError("reference path must be package-relative without traversal")
        if candidate.suffix.lower() not in _REFERENCE_SUFFIXES:
            raise ValueError("unsupported reference file type")
        normalized = candidate.as_posix()
        if any(existing.casefold() == normalized.casefold() for existing, _ in self._references):
            raise ValueError("duplicate or case-colliding reference path")
        self._references.append(
            (normalized, None if title is None else _prose(title, label="reference title"))
        )
        return self

    def snapshot(self, application: ApplicationMetadata) -> RecordedPluginSchema:
        if not self._references:
            raise ValueError("an opted-in plugin schema must contain at least one reference")
        short_product = normalized_short_product(application)
        options = tuple(self._expanded_option(option, short_product) for option in self._options)
        references = self._snapshot_references()
        reference_paths = {reference.path for reference in references}
        missing_routes = [
            route.reference for route in self._routes if route.reference not in reference_paths
        ]
        if missing_routes:
            raise ValueError(
                f"task routes reference unpackaged resources: {', '.join(missing_routes)}"
            )
        missing_kind_references = [
            item.reference for item in self._node_kinds if item.reference not in reference_paths
        ]
        if missing_kind_references:
            raise ValueError(
                "node kind declarations reference unpackaged resources: "
                + ", ".join(missing_kind_references)
            )
        distribution, version = _distribution(self.package)
        return RecordedPluginSchema(
            self.plugin_id,
            self.package,
            distribution,
            version,
            options,
            tuple(self._use_cases),
            tuple(self._rejections),
            references,
            tuple(self._expanded_annotation(item, short_product) for item in self._annotations),
            tuple(self._expanded_requirement(item, short_product) for item in self._requirements),
            tuple(self._routes),
            tuple(self._ordering),
            tuple(self._node_kinds),
        )

    def _expanded_option(self, option: OptionDeclaration, short_product: str) -> OptionDeclaration:
        return OptionDeclaration(
            option.kind,
            _expand(option.name, short_product),
            option.explanation,
            aliases=tuple(_expand(alias, short_product) for alias in option.aliases),
            command=None if option.command is None else _expand(option.command, short_product),
            scope=option.scope,
            value_mode=option.value_mode,
            values=option.values,
            explained_values=option.explained_values,
            required=option.required,
            repeatable=option.repeatable,
            has_default=option.has_default,
            default_json=option.default_json,
            deprecated=option.deprecated,
            replacement=(
                None if option.replacement is None else _expand(option.replacement, short_product)
            ),
        )

    @staticmethod
    def _expanded_annotation(
        annotation: SemanticAnnotation, short_product: str
    ) -> SemanticAnnotation:
        return SemanticAnnotation(
            _expand(annotation.subject, short_product),
            tuple(_expand(item, short_product) for item in annotation.commands),
            annotation.lifecycle,
            tuple(_expand(item, short_product) for item in annotation.requires),
            tuple(_expand(item, short_product) for item in annotation.conflicts_with),
            tuple(_expand(item, short_product) for item in annotation.implies),
            annotation.path_base,
            annotation.privilege,
            annotation.host_tools,
            annotation.shared_with,
            tuple(_expand(item, short_product) for item in annotation.examples),
        )

    @staticmethod
    def _expanded_requirement(
        requirement: RuntimeRequirement, short_product: str
    ) -> RuntimeRequirement:
        return RuntimeRequirement(
            requirement.kind,
            requirement.name,
            requirement.explanation,
            tuple(_expand(item, short_product) for item in requirement.commands),
        )

    def _snapshot_references(self) -> tuple[ReferenceSnapshot, ...]:
        module = importlib.import_module(self.package)
        total = 0
        snapshots: list[ReferenceSnapshot] = []
        for path, title in self._references:
            content = _read_resource(module, path)
            if len(content) > _MAX_REFERENCE_BYTES:
                raise ValueError(f"reference exceeds 1 MiB: {path}")
            total += len(content)
            if total > _MAX_PROVIDER_BYTES:
                raise ValueError("provider references exceed 8 MiB")
            content.decode("utf-8")
            snapshots.append(
                ReferenceSnapshot(path, title, content, hashlib.sha256(content).hexdigest())
            )
        return tuple(snapshots)

    def _require_command(self, command: str) -> None:
        if not any(
            option.kind is OptionKind.COMMAND and option.name == command for option in self._options
        ):
            raise ValueError(f"command must be declared first: {command}")

    @staticmethod
    def _validate_status(deprecated: bool, replacement: str | None) -> None:
        if type(deprecated) is not bool:
            raise TypeError("deprecated must be bool")
        if replacement is not None and not deprecated:
            raise ValueError("replacement requires deprecated=True")
        if replacement is not None and not isinstance(replacement, str):
            raise TypeError("replacement must be a string or None")


def _read_resource(module: ModuleType, path: str) -> bytes:
    resource = importlib.resources.files(module).joinpath(path)
    if resource.is_file():
        return resource.read_bytes()
    module_file = getattr(module, "__file__", None)
    if module_file is not None:
        package_dir = Path(module_file).resolve().parent
        if package_dir.parent.name == "src":
            source = package_dir.parent.parent / path
            if source.is_file() and not source.is_symlink():
                return source.read_bytes()
    raise FileNotFoundError(f"packaged schema reference is missing: {path}")


def _distribution(package: str) -> tuple[str, str]:
    candidates = importlib.metadata.packages_distributions().get(package, [])
    if len(candidates) == 1:
        distribution = candidates[0]
        try:
            return distribution, importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
    return package.replace("_", "-"), "source"


def _tokens(values: tuple[str, ...], *, label: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if type(values) is not tuple or any(
        not isinstance(item, str) or pattern.fullmatch(item) is None for item in values
    ):
        raise ValueError(f"{label} must be a tuple of valid tokens")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not contain duplicates")
    return values


def _prose_tuple(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be a tuple")
    normalized = tuple(_prose(item, label=label) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must not contain duplicates")
    return normalized
