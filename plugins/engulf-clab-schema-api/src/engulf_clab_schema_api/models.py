from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class ValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    POSITIVE_INTEGER = "positive-integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    NULL = "null"
    FILE_PATH = "file-path"
    DIRECTORY_PATH = "directory-path"
    URI = "uri"
    IP_ADDRESS = "ip-address"
    IPV4_ADDRESS = "ipv4-address"
    IPV6_ADDRESS = "ipv6-address"
    CIDR = "cidr"
    IPV4_CIDR = "ipv4-cidr"
    IPV6_CIDR = "ipv6-cidr"
    UUID = "uuid"
    IMAGE_REFERENCE = "image-reference"
    ENVIRONMENT_NAME = "environment-name"


@dataclass(frozen=True, slots=True)
class ExplainedValue:
    value: JsonScalar
    explanation: str


type ValueSpec = (
    tuple[JsonScalar | ExplainedValue, ...] | ValueType | tuple[ValueType | ExplainedValue, ...]
)


class SchemaScope(StrEnum):
    ROOT = "root"
    NODE = "node"
    LINK = "link"


class OptionKind(StrEnum):
    COMMAND = "command"
    CLI_ARGUMENT = "cli-argument"
    CLI_FLAG = "cli-flag"
    RUNTIME_VAR = "runtime-var"
    PROPERTY = "property"
    NODE_VAR = "node-var"


class ValueMode(StrEnum):
    LITERAL = "literal"
    TYPE = "type"


class LifecycleStage(StrEnum):
    BEFORE_GOAL = "before-goal"
    ANALYZE_CALL = "analyze-call"
    PREPARE_CALL = "prepare-call"
    WRAPPED_CALL = "wrapped-call"
    AFTER_CALL = "after-call"
    AFTER_GOAL = "after-goal"


class PathBase(StrEnum):
    TOPOLOGY_DIRECTORY = "topology-directory"
    INVOCATION_DIRECTORY = "invocation-directory"
    CONFIGURATION_ROOT = "configuration-root"
    USER_STATE = "user-state"
    WORKSPACE_STATE = "workspace-state"
    LICENSE_POOL = "license-pool"
    ABSOLUTE = "absolute"


class Privilege(StrEnum):
    NONE = "none"
    ROOT = "root"
    CONTAINER_RUNTIME = "container-runtime"


class UnsetType:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = UnsetType()


@dataclass(frozen=True, slots=True)
class OptionDeclaration:
    kind: OptionKind
    name: str
    explanation: str
    aliases: tuple[str, ...] = ()
    command: str | None = None
    scope: SchemaScope | None = None
    value_mode: ValueMode | None = None
    values: tuple[JsonScalar | str, ...] = ()
    explained_values: tuple[ExplainedValue, ...] = ()
    required: bool = False
    repeatable: bool = False
    has_default: bool = False
    default_json: str | None = None
    deprecated: bool = False
    replacement: str | None = None
    environment: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticAnnotation:
    subject: str
    commands: tuple[str, ...] = ()
    lifecycle: tuple[LifecycleStage, ...] = ()
    requires: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()
    path_base: PathBase | None = None
    privilege: Privilege | None = None
    host_tools: tuple[str, ...] = ()
    shared_with: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


class RequirementKind(StrEnum):
    HOST_TOOL = "host-tool"
    PRIVILEGE = "privilege"


@dataclass(frozen=True, slots=True)
class RuntimeRequirement:
    kind: RequirementKind
    name: str
    explanation: str
    commands: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskRoute:
    task: str
    reference: str
    explanation: str


@dataclass(frozen=True, slots=True)
class PluginOrdering:
    stage: LifecycleStage
    explanation: str
    after: tuple[str, ...] = ()
    before: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NodeKindDeclaration:
    kind: str
    explanation: str
    reference: str


@dataclass(frozen=True, slots=True)
class ReferenceSnapshot:
    path: str
    title: str | None
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class RecordedPluginSchema:
    plugin_id: str
    package: str
    distribution: str
    distribution_version: str
    options: tuple[OptionDeclaration, ...]
    use_cases: tuple[str, ...]
    rejections: tuple[str, ...]
    references: tuple[ReferenceSnapshot, ...]
    annotations: tuple[SemanticAnnotation, ...] = ()
    requirements: tuple[RuntimeRequirement, ...] = ()
    routes: tuple[TaskRoute, ...] = ()
    ordering: tuple[PluginOrdering, ...] = ()
    node_kinds: tuple[NodeKindDeclaration, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemaDeclarationFailure:
    plugin_id: str
    error: str


type SchemaRegistryEntry = RecordedPluginSchema | SchemaDeclarationFailure


class ContainerlabSourceKind(StrEnum):
    CHECKOUT = "checkout"
    BINARY = "binary"
    REPOSITORY = "repository"


@dataclass(frozen=True, slots=True)
class ContainerlabSourceHint:
    kind: ContainerlabSourceKind
    checkout: Path | None = None
    binary: Path | None = None
    repository: str | None = None
    revision: str | None = None
    resolved: bool = False


@dataclass(frozen=True, slots=True)
class VrnetlabSourceHint:
    checkout: Path | None = None
    repository: str | None = None
    revision: str | None = None
    resolved: bool = False


@dataclass(frozen=True, slots=True)
class SchemaBuildRequest:
    requester_plugin_id: str
    request_id: str
    required: bool = True
    current_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledReference:
    plugin_id: str
    path: str
    title: str | None
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class CompiledPluginSchema:
    plugin_id: str
    path: str
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class CompiledSchemaBundle:
    fingerprint: str
    manifest: bytes
    topology_schema: bytes
    catalog_json: bytes
    catalog_markdown: bytes
    references: tuple[CompiledReference, ...]
    plugin_schemas: tuple[CompiledPluginSchema, ...] = ()
