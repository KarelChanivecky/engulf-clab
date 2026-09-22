"""Runtime Containerlab and Engulf plugin schema generator."""

from .cache import bundle_directory_complete
from .compiler import FORMAT_VERSION, SchemaCompilationError, compile_schema_bundle
from .node_kinds import NODE_KIND_ALLOWLIST_ENVIRONMENT
from .plugin import SchemaGeneratorPlugin, plugin
from .source import BaseSchema, SchemaSourceError, resolve_base_schema, source_hint_from_environment

__all__ = [
    "FORMAT_VERSION",
    "NODE_KIND_ALLOWLIST_ENVIRONMENT",
    "BaseSchema",
    "SchemaCompilationError",
    "SchemaGeneratorPlugin",
    "SchemaSourceError",
    "bundle_directory_complete",
    "compile_schema_bundle",
    "plugin",
    "resolve_base_schema",
    "source_hint_from_environment",
]
