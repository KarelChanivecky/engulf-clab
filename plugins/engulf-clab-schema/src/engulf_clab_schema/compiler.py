from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any, cast

import yaml  # type: ignore[import-untyped]
from engulf_api import ApplicationMetadata
from engulf_clab_schema_api import (
    CompiledPluginSchema,
    CompiledReference,
    CompiledSchemaBundle,
    OptionDeclaration,
    OptionKind,
    RecordedPluginSchema,
    SchemaDeclarationFailure,
    SchemaRegistryEntry,
    SchemaScope,
    SemanticAnnotation,
    ValueMode,
    ValueType,
    split_property_path,
)

from .node_kinds import NODE_KIND_PROVIDER_ID, NodeKindCatalog, NodeKindRecord, SourceIdentity
from .source import BaseSchema

FORMAT_VERSION = 1
COMPILER_VERSION = "3"


class SchemaCompilationError(RuntimeError):
    pass


def compile_schema_bundle(
    application: ApplicationMetadata,
    base: BaseSchema,
    entries: Iterable[SchemaRegistryEntry],
    node_kinds: NodeKindCatalog | None = None,
) -> CompiledSchemaBundle:
    providers: list[RecordedPluginSchema] = []
    failures: list[SchemaDeclarationFailure] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.plugin_id in seen:
            raise SchemaCompilationError(f"duplicate schema provider: {entry.plugin_id}")
        seen.add(entry.plugin_id)
        if isinstance(entry, SchemaDeclarationFailure):
            failures.append(entry)
        elif isinstance(entry, RecordedPluginSchema):
            providers.append(entry)
        else:
            raise SchemaCompilationError("invalid schema registry entry")
    if failures:
        detail = "; ".join(f"{item.plugin_id}: {item.error}" for item in failures)
        raise SchemaCompilationError(f"incomplete plugin schema contributions: {detail}")
    providers.sort(key=lambda item: item.plugin_id)
    _validate_node_kind_declarations(providers, node_kinds)
    provider_schemas = tuple(_compiled_plugin_schema(provider) for provider in providers)
    plugin_schema_index = {item.plugin_id: item for item in provider_schemas}
    upstream_schema = (
        None if node_kinds is None else _compiled_node_kind_schema(node_kinds, providers)
    )
    plugin_schemas = provider_schemas + (() if upstream_schema is None else (upstream_schema,))
    fingerprint_input = {
        "format": FORMAT_VERSION,
        "compiler": COMPILER_VERSION,
        "application": _application(application),
        "containerlab": _source(base),
        "node_kinds": None if node_kinds is None else _node_kind_fingerprint(node_kinds),
        "plugins": [
            _provider_manifest(
                provider,
                include_reference_content=True,
                plugin_schema=plugin_schema_index[provider.plugin_id],
            )
            for provider in providers
        ],
    }
    fingerprint = hashlib.sha256(_json_bytes(fingerprint_input)).hexdigest()
    manifest = {
        "format": "engulf-clab-runtime-schema",
        "version": FORMAT_VERSION,
        "fingerprint": fingerprint,
        "application": _application(application),
        "containerlab": _source(base),
        "node_kinds": (
            None
            if node_kinds is None or upstream_schema is None
            else _node_kind_manifest(node_kinds, upstream_schema, providers)
        ),
        "plugins": [
            _provider_manifest(
                provider,
                include_reference_content=False,
                plugin_schema=plugin_schema_index[provider.plugin_id],
            )
            for provider in providers
        ],
        "paths": _path_index(providers),
    }
    catalog = _catalog(
        application,
        base,
        providers,
        plugin_schema_index,
        fingerprint,
        node_kinds,
        upstream_schema,
    )
    schema = _compose_schema(base.document, providers, fingerprint)
    references = tuple(
        CompiledReference(
            provider.plugin_id,
            reference.path,
            reference.title,
            reference.content,
            reference.sha256,
        )
        for provider in providers
        for reference in provider.references
    ) + (() if node_kinds is None else _compiled_node_kind_references(node_kinds, providers))
    if sum(len(item.content) for item in references) > 32 * 1024 * 1024:
        raise SchemaCompilationError("compiled references exceed 32 MiB")
    return CompiledSchemaBundle(
        fingerprint=fingerprint,
        manifest=_json_bytes(manifest),
        topology_schema=_json_bytes(schema),
        catalog_json=_json_bytes(catalog),
        catalog_markdown=_catalog_markdown(catalog).encode(),
        references=references,
        plugin_schemas=plugin_schemas,
    )


def _application(application: ApplicationMetadata) -> dict[str, str]:
    return {
        "application_id": application.application_id,
        "display_name": application.display_name,
        "vendor": application.vendor,
        "product": application.product,
        "short_product_name": application.short_product_name,
        "version": application.version,
    }


def _source(base: BaseSchema) -> dict[str, object]:
    return {
        "kind": base.source_kind,
        "repository": base.repository,
        "revision": base.revision,
        "version": base.version,
        "dirty": base.dirty,
        "sha256": base.sha256,
    }


def _provider_manifest(
    provider: RecordedPluginSchema,
    *,
    include_reference_content: bool,
    plugin_schema: CompiledPluginSchema,
) -> dict[str, object]:
    references: list[dict[str, object]] = []
    for reference in provider.references:
        item: dict[str, object] = {
            "path": reference.path,
            "title": reference.title,
            "sha256": reference.sha256,
        }
        if include_reference_content:
            item["content_sha256"] = hashlib.sha256(reference.content).hexdigest()
        references.append(item)
    return {
        "plugin_id": provider.plugin_id,
        "package": provider.package,
        "distribution": provider.distribution,
        "distribution_version": provider.distribution_version,
        "agent_schema": {
            "path": f"plugins/{provider.plugin_id}/{plugin_schema.path}",
            "sha256": plugin_schema.sha256,
        },
        "options": [
            _option_manifest(
                option,
                next(
                    (item for item in provider.annotations if item.subject == option.name),
                    None,
                ),
            )
            for option in provider.options
        ],
        "use_cases": list(provider.use_cases),
        "rejections": list(provider.rejections),
        "references": references,
        "requirements": [
            {
                "kind": item.kind.value,
                "name": item.name,
                "explanation": item.explanation,
                "commands": list(item.commands),
            }
            for item in provider.requirements
        ],
        "routes": [
            {
                "task": item.task,
                "reference": item.reference,
                "explanation": item.explanation,
            }
            for item in provider.routes
        ],
        "ordering": [
            {
                "stage": item.stage.value,
                "after": list(item.after),
                "before": list(item.before),
                "explanation": item.explanation,
            }
            for item in provider.ordering
        ],
        "node_kinds": [
            {
                "kind": item.kind,
                "explanation": item.explanation,
                "reference": item.reference,
            }
            for item in provider.node_kinds
        ],
    }


def _option_manifest(
    option: OptionDeclaration, annotation: SemanticAnnotation | None
) -> dict[str, object]:
    result: dict[str, object] = {
        "kind": option.kind.value,
        "name": option.name,
        "explanation": option.explanation,
        "aliases": list(option.aliases),
        "command": option.command,
        "scope": None if option.scope is None else option.scope.value,
        "value_mode": None if option.value_mode is None else option.value_mode.value,
        "values": list(option.values),
        "explained_values": [
            {"value": item.value, "explanation": item.explanation}
            for item in option.explained_values
        ],
        "required": option.required,
        "repeatable": option.repeatable,
        "deprecated": option.deprecated,
        "replacement": option.replacement,
        "environment_default": option.environment,
    }
    if option.has_default:
        result["default"] = json.loads(option.default_json or "null")
    if annotation is not None:
        result["semantics"] = {
            "commands": list(annotation.commands),
            "lifecycle": [item.value for item in annotation.lifecycle],
            "requires": list(annotation.requires),
            "conflicts_with": list(annotation.conflicts_with),
            "implies": list(annotation.implies),
            "path_base": None if annotation.path_base is None else annotation.path_base.value,
            "privilege": None if annotation.privilege is None else annotation.privilege.value,
            "host_tools": list(annotation.host_tools),
            "shared_with": list(annotation.shared_with),
            "examples": list(annotation.examples),
        }
    return result


def _compiled_plugin_schema(provider: RecordedPluginSchema) -> CompiledPluginSchema:
    if any(reference.path == "schema.yaml" for reference in provider.references):
        raise SchemaCompilationError(
            f"plugin reference collides with generated schema: {provider.plugin_id}/schema.yaml"
        )
    content = yaml.safe_dump(
        _plugin_agent_document(provider),
        sort_keys=False,
        allow_unicode=True,
        width=1000,
    ).encode()
    return CompiledPluginSchema(
        provider.plugin_id,
        "schema.yaml",
        content,
        hashlib.sha256(content).hexdigest(),
    )


def _plugin_agent_document(provider: RecordedPluginSchema) -> dict[str, object]:
    annotations = {item.subject: item for item in provider.annotations}
    commands: dict[str, dict[str, object]] = {}
    global_flags: dict[str, object] = {}
    runtime: dict[str, object] = {}
    root_properties: dict[str, object] = {}
    node_properties: dict[str, object] = {}
    node_environment: dict[str, object] = {}
    link_properties: dict[str, object] = {}
    for option in provider.options:
        control = _agent_control(option, annotations.get(option.name))
        if option.kind is OptionKind.COMMAND:
            commands[option.name] = control
        elif option.kind in {OptionKind.CLI_ARGUMENT, OptionKind.CLI_FLAG}:
            if option.command is None:
                global_flags[option.name] = control
            else:
                command = commands.setdefault(option.command, {})
                key = "arguments" if option.kind is OptionKind.CLI_ARGUMENT else "flags"
                cast(dict[str, object], command.setdefault(key, {}))[option.name] = control
        elif option.kind is OptionKind.RUNTIME_VAR:
            runtime[option.name] = control
        elif option.kind is OptionKind.NODE_VAR:
            node_environment[option.name] = control
        elif option.kind is OptionKind.PROPERTY and option.scope is not None:
            target = {
                SchemaScope.ROOT: root_properties,
                SchemaScope.NODE: node_properties,
                SchemaScope.LINK: link_properties,
            }[option.scope]
            target[option.name] = control

    document: dict[str, object] = {
        "format": "engulf-clab-plugin-capabilities",
        "version": 1,
        "plugin": {
            "id": provider.plugin_id,
            "distribution": provider.distribution,
            "version": provider.distribution_version,
        },
    }
    _put(document, "use_when", list(provider.use_cases))
    _put(document, "avoid_when", list(provider.rejections))
    _put(
        document,
        "requirements",
        [
            _without_empty(
                {
                    "kind": item.kind.value,
                    "name": item.name,
                    "commands": list(item.commands),
                    "explanation": item.explanation,
                }
            )
            for item in provider.requirements
        ],
    )
    _put(
        document,
        "ordering",
        [
            _without_empty(
                {
                    "stage": item.stage.value,
                    "after": list(item.after),
                    "before": list(item.before),
                    "explanation": item.explanation,
                }
            )
            for item in provider.ordering
        ],
    )
    _put(document, "commands", commands)
    _put(document, "global_flags", global_flags)
    _put(document, "runtime", runtime)
    _put(
        document,
        "topology",
        _without_empty(
            {
                "root": _without_empty({"properties": root_properties}),
                "node": _without_empty({"properties": node_properties, "env": node_environment}),
                "link": _without_empty({"properties": link_properties}),
            }
        ),
    )
    _put(
        document,
        "tasks",
        {
            item.task: {"reference": item.reference, "explanation": item.explanation}
            for item in provider.routes
        },
    )
    _put(
        document,
        "node_kinds",
        {
            item.kind: {
                "description": item.explanation,
                "reference": item.reference,
            }
            for item in provider.node_kinds
        },
    )
    _put(
        document,
        "references",
        [_without_empty({"path": item.path, "title": item.title}) for item in provider.references],
    )
    return document


def _agent_control(
    option: OptionDeclaration, annotation: SemanticAnnotation | None
) -> dict[str, object]:
    result: dict[str, object] = {"description": option.explanation}
    if option.value_mode is ValueMode.TYPE:
        key = "type" if len(option.values) == 1 else "types"
        result[key] = option.values[0] if len(option.values) == 1 else list(option.values)
    elif option.value_mode is ValueMode.LITERAL:
        explanations = {
            json.dumps(item.value, sort_keys=True, allow_nan=False): item.explanation
            for item in option.explained_values
        }
        result["values"] = [
            (
                {"value": value, "description": explanations[encoded]}
                if (encoded := json.dumps(value, sort_keys=True, allow_nan=False)) in explanations
                else value
            )
            for value in option.values
        ]
    if option.value_mode is ValueMode.TYPE and option.explained_values:
        result["recognized_values"] = [
            {"value": item.value, "description": item.explanation}
            for item in option.explained_values
        ]
    _put(result, "aliases", list(option.aliases))
    if option.required:
        result["required"] = True
    if option.repeatable:
        result["repeatable"] = True
    if option.has_default:
        result["default"] = json.loads(option.default_json or "null")
    if option.deprecated:
        result["deprecated"] = True
    if option.replacement is not None:
        result["replacement"] = option.replacement
    if option.environment is not None:
        result["environment_default"] = option.environment
    if annotation is not None:
        _put(result, "commands", list(annotation.commands))
        _put(result, "lifecycle", [item.value for item in annotation.lifecycle])
        _put(result, "requires", list(annotation.requires))
        _put(result, "conflicts_with", list(annotation.conflicts_with))
        _put(result, "implies", list(annotation.implies))
        if annotation.path_base is not None:
            result["path_base"] = annotation.path_base.value
        if annotation.privilege is not None:
            result["privilege"] = annotation.privilege.value
        _put(result, "host_tools", list(annotation.host_tools))
        _put(result, "shared_with", list(annotation.shared_with))
        _put(result, "examples", list(annotation.examples))
    return result


def _put(target: dict[str, object], key: str, value: object) -> None:
    if value not in (None, [], {}, ()):
        target[key] = value


def _without_empty(source: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in source.items() if value not in (None, [], {}, ())}


def _validate_node_kind_declarations(
    providers: Iterable[RecordedPluginSchema], node_kinds: NodeKindCatalog | None
) -> None:
    if node_kinds is None:
        return
    available = {item.kind for item in node_kinds.kinds}
    missing = [
        f"{provider.plugin_id}:{item.kind}"
        for provider in providers
        for item in provider.node_kinds
        if item.kind not in available
    ]
    if missing:
        raise SchemaCompilationError(
            "plugin node-kind guidance is unavailable in the selected Containerlab source: "
            + ", ".join(missing)
        )


def _source_identity(source: SourceIdentity) -> dict[str, object]:
    return {
        "kind": source.kind,
        "repository": source.repository,
        "revision": source.revision,
        "dirty": source.dirty,
        "sha256": source.sha256,
    }


def _node_kind_fingerprint(catalog: NodeKindCatalog) -> dict[str, object]:
    return {
        "containerlab": _source_identity(catalog.containerlab),
        "vrnetlab": _source_identity(catalog.vrnetlab),
        "kinds": [
            {
                "kind": item.kind,
                "summary": item.summary,
                "containerlab_path": item.containerlab_path,
                "containerlab_sha256": _optional_sha256(item.containerlab_content),
                "vrnetlab_path": item.vrnetlab_path,
                "vrnetlab_sha256": _optional_sha256(item.vrnetlab_content),
            }
            for item in catalog.kinds
        ],
    }


def _node_kind_manifest(
    catalog: NodeKindCatalog,
    schema: CompiledPluginSchema,
    providers: Iterable[RecordedPluginSchema],
) -> dict[str, object]:
    return {
        "provider_id": NODE_KIND_PROVIDER_ID,
        "agent_schema": {
            "path": f"plugins/{NODE_KIND_PROVIDER_ID}/{schema.path}",
            "sha256": schema.sha256,
        },
        "references": [
            {
                "path": f"plugins/{item.plugin_id}/{item.path}",
                "title": item.title,
                "sha256": item.sha256,
            }
            for item in _compiled_node_kind_references(catalog, providers)
        ],
        **_node_kind_fingerprint(catalog),
    }


def _compiled_node_kind_schema(
    catalog: NodeKindCatalog, providers: Iterable[RecordedPluginSchema]
) -> CompiledPluginSchema:
    content = yaml.safe_dump(
        {
            "format": "engulf-clab-node-kind-index",
            "version": 1,
            "sources": {
                "containerlab": _source_identity(catalog.containerlab),
                "vrnetlab": _source_identity(catalog.vrnetlab),
            },
            "kinds": {
                item.kind: _without_empty(
                    {
                        "description": item.summary,
                        "schema": f"node-kinds/{item.kind}/schema.yaml",
                        "containerlab": (
                            None
                            if item.containerlab_content is None
                            else f"node-kinds/{item.kind}/containerlab.md"
                        ),
                        "vrnetlab": (
                            None
                            if item.vrnetlab_content is None
                            else f"node-kinds/{item.kind}/vrnetlab.md"
                        ),
                        "augmentations": _node_kind_augmentations(item.kind, providers),
                    }
                )
                for item in catalog.kinds
            },
        },
        sort_keys=False,
        allow_unicode=True,
        width=1000,
    ).encode()
    return CompiledPluginSchema(
        NODE_KIND_PROVIDER_ID,
        "schema.yaml",
        content,
        hashlib.sha256(content).hexdigest(),
    )


def _compiled_node_kind_references(
    catalog: NodeKindCatalog,
    providers: Iterable[RecordedPluginSchema],
) -> tuple[CompiledReference, ...]:
    result: list[CompiledReference] = []
    for item in catalog.kinds:
        schema_path = f"node-kinds/{item.kind}/schema.yaml"
        schema = yaml.safe_dump(
            _node_kind_document(item, catalog, providers),
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        ).encode()
        result.append(
            CompiledReference(
                NODE_KIND_PROVIDER_ID,
                schema_path,
                f"{item.kind} source guidance",
                schema,
                hashlib.sha256(schema).hexdigest(),
            )
        )
        for name, content in (
            ("containerlab.md", item.containerlab_content),
            ("vrnetlab.md", item.vrnetlab_content),
        ):
            if content is None:
                continue
            path = f"node-kinds/{item.kind}/{name}"
            result.append(
                CompiledReference(
                    NODE_KIND_PROVIDER_ID,
                    path,
                    f"{item.kind} {name.removesuffix('.md')} guidance",
                    content,
                    hashlib.sha256(content).hexdigest(),
                )
            )
    return tuple(result)


def _node_kind_document(
    item: NodeKindRecord,
    catalog: NodeKindCatalog,
    providers: Iterable[RecordedPluginSchema],
) -> dict[str, object]:
    return _without_empty(
        {
            "format": "engulf-clab-node-kind",
            "version": 1,
            "kind": item.kind,
            "description": item.summary,
            "containerlab": _without_empty(
                {
                    "source_path": item.containerlab_path,
                    "reference": (
                        "containerlab.md" if item.containerlab_content is not None else None
                    ),
                    "revision": catalog.containerlab.revision,
                }
            ),
            "vrnetlab": _without_empty(
                {
                    "source_path": item.vrnetlab_path,
                    "reference": "vrnetlab.md" if item.vrnetlab_content is not None else None,
                    "revision": catalog.vrnetlab.revision,
                }
            ),
            "augmentations": _node_kind_augmentations(item.kind, providers),
        }
    )


def _node_kind_augmentations(
    kind: str, providers: Iterable[RecordedPluginSchema]
) -> list[dict[str, str]]:
    return [
        {
            "plugin_id": provider.plugin_id,
            "description": declaration.explanation,
            "schema": f"plugins/{provider.plugin_id}/schema.yaml",
            "reference": f"plugins/{provider.plugin_id}/{declaration.reference}",
        }
        for provider in providers
        for declaration in provider.node_kinds
        if declaration.kind == kind
    ]


def _optional_sha256(content: bytes | None) -> str | None:
    return None if content is None else hashlib.sha256(content).hexdigest()


def _catalog(
    application: ApplicationMetadata,
    base: BaseSchema,
    providers: list[RecordedPluginSchema],
    plugin_schemas: dict[str, CompiledPluginSchema],
    fingerprint: str,
    node_kinds: NodeKindCatalog | None,
    node_kind_schema: CompiledPluginSchema | None,
) -> dict[str, object]:
    routes: dict[str, list[dict[str, str]]] = defaultdict(list)
    provider_items: list[dict[str, object]] = []
    for provider in providers:
        for route in provider.routes:
            routes[route.task].append(
                {
                    "plugin_id": provider.plugin_id,
                    "explanation": route.explanation,
                    "schema": f"plugins/{provider.plugin_id}/{plugin_schemas[provider.plugin_id].path}",
                    "reference": f"plugins/{provider.plugin_id}/{route.reference}",
                }
            )
        provider_items.append(
            {
                "plugin_id": provider.plugin_id,
                "distribution": provider.distribution,
                "version": provider.distribution_version,
                "schema": f"plugins/{provider.plugin_id}/{plugin_schemas[provider.plugin_id].path}",
                "use_when": list(provider.use_cases),
                "avoid_when": list(provider.rejections),
            }
        )
    return {
        "format": "engulf-clab-runtime-catalog",
        "version": 1,
        "fingerprint": fingerprint,
        "application": _application(application),
        "containerlab": _source(base),
        "base_cli": {
            "authoritative_command": f"{application.short_product_name} --help",
            "explanation": "Discover base Containerlab commands and flags from the selected runtime before constructing a call.",
        },
        "node_kinds": (
            None
            if node_kinds is None or node_kind_schema is None
            else {
                "schema": f"plugins/{NODE_KIND_PROVIDER_ID}/{node_kind_schema.path}",
                "containerlab": _source_identity(node_kinds.containerlab),
                "vrnetlab": _source_identity(node_kinds.vrnetlab),
                "count": len(node_kinds.kinds),
            }
        ),
        "tasks": {key: routes[key] for key in sorted(routes)},
        "providers": provider_items,
    }


def _catalog_markdown(catalog: dict[str, object]) -> str:
    application = cast(dict[str, object], catalog["application"])
    source = cast(dict[str, object], catalog["containerlab"])
    base_cli = cast(dict[str, str], catalog["base_cli"])
    lines = [
        "# Installed lab runtime catalog",
        "",
        f"Fingerprint: `{catalog['fingerprint']}`",
        f"Application: `{application['short_product_name']}` `{application['version']}`",
        f"Containerlab source: `{source['kind']}` revision `{source['revision']}`",
        f"Base CLI inventory: `{base_cli['authoritative_command']}` — {base_cli['explanation']}",
        "",
        "Use the task routes or provider directory to select compact plugin YAML files. The composed",
        "`clab.schema.json` is the final validation authority, not the primary discovery surface.",
        "",
    ]
    node_kinds = catalog.get("node_kinds")
    if isinstance(node_kinds, dict):
        containerlab = cast(dict[str, object], node_kinds["containerlab"])
        vrnetlab = cast(dict[str, object], node_kinds["vrnetlab"])
        lines.extend(
            [
                "## Node-kind routing",
                "",
                f"Read `{node_kinds['schema']}` when a topology uses a specialized `kind:`. It",
                "routes to one small kind record and only the upstream documents available in the",
                "selected repositories.",
                "",
                f"Containerlab node guidance revision: `{containerlab['revision']}`",
                f"vrnetlab builder guidance revision: `{vrnetlab['revision']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Task routing",
            "",
            "| Task | Provider | Capabilities | Detailed reference | Why |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    tasks = cast(dict[str, list[dict[str, str]]], catalog["tasks"])
    for task, routes in tasks.items():
        for route in routes:
            lines.append(
                f"| `{task}` | `{route['plugin_id']}` | `{route['schema']}` | "
                f"`{route['reference']}` | "
                f"{_markdown(route['explanation'])} |"
            )
    if not tasks:
        lines.append("| none declared | | | | |")
    lines.extend(
        [
            "",
            "## Provider directory",
            "",
            "Use this table when the task wording does not match a route exactly.",
            "",
            "| Provider | Use when | Avoid when | Capabilities |",
            "| --- | --- | --- | --- |",
        ]
    )
    providers = cast(list[dict[str, object]], catalog["providers"])
    for provider in providers:
        use_when = "<br>".join(cast(list[str], provider["use_when"])) or "No guidance declared."
        avoid_when = (
            "<br>".join(cast(list[str], provider["avoid_when"])) or "No exclusions declared."
        )
        lines.append(
            f"| `{provider['plugin_id']}` | {_markdown(use_when)} | "
            f"{_markdown(avoid_when)} | `{provider['schema']}` |"
        )
    return "\n".join(lines) + "\n"


def _markdown(value: str) -> str:
    return value.replace("|", "\\|")


def _path_index(
    providers: list[RecordedPluginSchema],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    result: dict[str, dict[str, list[dict[str, str]]]] = {scope.value: {} for scope in SchemaScope}
    for provider in providers:
        for option in provider.options:
            if option.kind is OptionKind.NODE_VAR:
                scope = SchemaScope.NODE
                path = f"env.{option.name}"
            elif option.kind is OptionKind.PROPERTY and option.scope is not None:
                scope = option.scope
                path = option.name
            else:
                continue
            result[scope.value].setdefault(path, []).append(
                {"plugin_id": provider.plugin_id, "explanation": option.explanation}
            )
    return result


def _compose_schema(
    base_document: dict[str, object],
    providers: list[RecordedPluginSchema],
    fingerprint: str,
) -> dict[str, object]:
    document: dict[str, Any] = copy.deepcopy(base_document)
    document["x-eclab-fingerprint"] = fingerprint
    document["x-eclab-manifest"] = "manifest.json"
    mutable_definitions: set[str] = set()
    scoped: dict[tuple[SchemaScope, tuple[str, ...]], list[tuple[str, OptionDeclaration]]] = (
        defaultdict(list)
    )
    for provider in providers:
        for option in provider.options:
            if option.kind is OptionKind.NODE_VAR:
                scoped[(SchemaScope.NODE, ("env", option.name))].append(
                    (provider.plugin_id, option)
                )
            elif option.kind is OptionKind.PROPERTY and option.scope is not None:
                scoped[(option.scope, split_property_path(option.name))].append(
                    (provider.plugin_id, option)
                )
    roots: dict[SchemaScope, dict[str, Any]] = {SchemaScope.ROOT: document}
    if any(scope is SchemaScope.NODE for scope, _ in scoped):
        roots[SchemaScope.NODE] = _explicit_node_schema(document, mutable_definitions)
    if any(scope is SchemaScope.LINK for scope, _ in scoped):
        roots[SchemaScope.LINK] = _link_overlay(document)
    for (scope, path), declarations in sorted(
        scoped.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        _install_path(
            document,
            roots[scope],
            path,
            declarations,
            scope,
            mutable_definitions,
        )
    _prune_generated_definitions(document, mutable_definitions)
    return document


def _explicit_node_schema(
    document: dict[str, Any], mutable_definitions: set[str]
) -> dict[str, Any]:
    definitions = _mapping(document, "definitions")
    source = definitions.get("node-config")
    if not isinstance(source, dict):
        raise SchemaCompilationError("Containerlab schema has no node-config definition")
    name = "eclab-explicit-node-config"
    definitions[name] = copy.deepcopy(source)
    mutable_definitions.add(name)
    topology = _mapping(_mapping(document, "properties"), "topology")
    topology_properties = _mapping(topology, "properties")
    nodes = _mapping(topology_properties, "nodes")
    patterns = _mapping(nodes, "patternProperties")
    for node_schema in patterns.values():
        if not isinstance(node_schema, dict):
            continue
        for keyword in ("oneOf", "anyOf"):
            alternatives = node_schema.get(keyword)
            if not isinstance(alternatives, list):
                continue
            for alternative in alternatives:
                if (
                    isinstance(alternative, dict)
                    and alternative.get("$ref") == "#/definitions/node-config"
                ):
                    alternative["$ref"] = f"#/definitions/{name}"
    return cast(dict[str, Any], definitions[name])


def _link_overlay(document: dict[str, Any]) -> dict[str, Any]:
    topology = _mapping(_mapping(document, "properties"), "topology")
    links = _mapping(_mapping(topology, "properties"), "links")
    original = links.get("items")
    if not isinstance(original, dict):
        raise SchemaCompilationError("Containerlab schema has no link item schema")
    overlay: dict[str, Any] = {"type": "object", "properties": {}}
    links["items"] = {"allOf": [original, overlay]}
    return overlay


def _install_path(
    document: dict[str, Any],
    root: dict[str, Any],
    path: tuple[str, ...],
    declarations: list[tuple[str, OptionDeclaration]],
    scope: SchemaScope,
    mutable_definitions: set[str],
) -> None:
    current = root
    for index, segment in enumerate(path[:-1]):
        current = _dereference_for_mutation(
            document,
            current,
            f"{scope.value}-{index}-{segment}",
            mutable_definitions,
        )
        properties = current.setdefault("properties", {})
        if not isinstance(properties, dict):
            raise SchemaCompilationError(
                f"schema properties are invalid at {'.'.join(path[:index])}"
            )
        child = properties.get(segment)
        if child is None:
            child = {"type": "object", "properties": {}}
            properties[segment] = child
        if not isinstance(child, dict):
            raise SchemaCompilationError(
                f"schema path is not an object: {'.'.join(path[: index + 1])}"
            )
        current = child
    current = _dereference_for_mutation(
        document,
        current,
        f"{scope.value}-final-parent",
        mutable_definitions,
    )
    final = path[-1]
    branches = [_provider_branch(plugin_id, option) for plugin_id, option in declarations]
    if "*" in final:
        patterns = current.setdefault("patternProperties", {})
        if not isinstance(patterns, dict):
            raise SchemaCompilationError("schema patternProperties is not an object")
        pattern = _glob_pattern(final)
        existing = patterns.get(pattern)
        patterns[pattern] = _combine(existing, branches)
    else:
        properties = current.setdefault("properties", {})
        if not isinstance(properties, dict):
            raise SchemaCompilationError("schema properties is not an object")
        properties[final] = _combine(properties.get(final), branches)


def _dereference_for_mutation(
    document: dict[str, Any],
    schema: dict[str, Any],
    suffix: str,
    mutable_definitions: set[str],
) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/definitions/"):
        return schema
    definitions = _mapping(document, "definitions")
    original_name = reference.removeprefix("#/definitions/")
    original = definitions.get(original_name)
    if not isinstance(original, dict):
        raise SchemaCompilationError(f"unresolved schema reference: {reference}")
    if original_name in mutable_definitions:
        return original
    safe = re.sub(r"[^a-z0-9-]+", "-", suffix.lower()).strip("-")
    candidate = f"eclab-{safe}-{original_name}"
    name = candidate
    counter = 2
    while name in definitions:
        name = f"{candidate}-{counter}"
        counter += 1
    clone = copy.deepcopy(original)
    definitions[name] = clone
    mutable_definitions.add(name)
    schema.clear()
    schema["$ref"] = f"#/definitions/{name}"
    return clone


def _prune_generated_definitions(document: dict[str, Any], generated: set[str]) -> None:
    definitions = _mapping(document, "definitions")
    root = {key: value for key, value in document.items() if key != "definitions"}
    reachable = set(_definition_references(root))
    pending = list(reachable)
    while pending:
        name = pending.pop()
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            continue
        for reference in _definition_references(definition):
            if reference not in reachable:
                reachable.add(reference)
                pending.append(reference)
    for name in generated - reachable:
        definitions.pop(name, None)


def _definition_references(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith("#/definitions/"):
                yield item.removeprefix("#/definitions/")
            else:
                yield from _definition_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _definition_references(item)


def _provider_branch(plugin_id: str, option: OptionDeclaration) -> dict[str, Any]:
    value_schema = _value_schema(option)
    value_schema["title"] = plugin_id
    value_schema["description"] = option.explanation
    value_schema["x-eclab-plugin-id"] = plugin_id
    if option.required:
        value_schema["x-eclab-required"] = True
    if option.has_default:
        value_schema["default"] = json.loads(option.default_json or "null")
    if option.deprecated:
        value_schema["deprecated"] = True
    if option.replacement is not None:
        value_schema["x-eclab-replacement"] = option.replacement
    return value_schema


def _value_schema(option: OptionDeclaration) -> dict[str, Any]:
    if option.value_mode is ValueMode.LITERAL:
        return {"enum": list(option.values)}
    schemas = [
        _type_schema(
            ValueType(cast(str, value)),
            string_encoded=option.kind is OptionKind.NODE_VAR,
        )
        for value in option.values
    ]
    if len(schemas) == 1:
        return schemas[0]
    return {"anyOf": schemas}


def _type_schema(value: ValueType, *, string_encoded: bool) -> dict[str, Any]:
    if string_encoded:
        patterns = {
            ValueType.INTEGER: r"^-?[0-9]+$",
            ValueType.POSITIVE_INTEGER: r"^[1-9][0-9]*$",
            ValueType.NUMBER: r"^-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$",
            ValueType.BOOLEAN: r"^(?:true|false|1|0|yes|no|on|off)$",
        }
        result: dict[str, Any] = {"type": "string", "x-eclab-value-type": value.value}
        if value in patterns:
            result["pattern"] = patterns[value]
        return result
    primitive = {
        ValueType.STRING: "string",
        ValueType.INTEGER: "integer",
        ValueType.POSITIVE_INTEGER: "integer",
        ValueType.NUMBER: "number",
        ValueType.BOOLEAN: "boolean",
        ValueType.ARRAY: "array",
        ValueType.OBJECT: "object",
        ValueType.NULL: "null",
    }
    if value in primitive:
        result = {"type": primitive[value]}
        if value is ValueType.POSITIVE_INTEGER:
            result["minimum"] = 1
        return result
    formats = {
        ValueType.URI: "uri",
        ValueType.IPV4_ADDRESS: "ipv4",
        ValueType.IPV6_ADDRESS: "ipv6",
        ValueType.UUID: "uuid",
    }
    if value is ValueType.IP_ADDRESS:
        return {
            "anyOf": [{"type": "string", "format": "ipv4"}, {"type": "string", "format": "ipv6"}]
        }
    result = {"type": "string", "x-eclab-value-type": value.value}
    if value in formats:
        result["format"] = formats[value]
    if value in {ValueType.CIDR, ValueType.IPV4_CIDR, ValueType.IPV6_CIDR}:
        result["pattern"] = r"^.+/[0-9]+$"
    if value is ValueType.ENVIRONMENT_NAME:
        result["pattern"] = r"^[A-Za-z_][A-Za-z0-9_]*$"
    return result


def _combine(existing: object, branches: list[dict[str, Any]]) -> dict[str, Any]:
    if existing is None:
        return branches[0] if len(branches) == 1 else {"anyOf": branches}
    if not isinstance(existing, dict):
        raise SchemaCompilationError("existing schema branch is not an object")
    return {"anyOf": [existing, *branches]}


def _glob_pattern(value: str) -> str:
    prefix, suffix = value.split("*", 1)
    return f"^{re.escape(prefix)}.+{re.escape(suffix)}$"


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise SchemaCompilationError(f"Containerlab schema field is not an object: {key}")
    return value


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
