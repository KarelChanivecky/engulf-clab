from __future__ import annotations

import importlib.metadata
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

POOL_METADATA_FILENAME = ".lic-pool"
POOL_METADATA_VERSION = 1
POOL_METADATA_CONTRIBUTOR_GROUP = "engulf_clab.license_pool.metadata.v1"
_CONTRIBUTOR_ID = re.compile(r"[a-z0-9]+(?:[._][a-z0-9]+)*\Z")
_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")


class LicensePoolMetadataError(RuntimeError):
    """A contributor or shared pool metadata document is invalid."""


class LicensePoolVariableType(StrEnum):
    """Supported types for automatically collected pool metadata variables."""

    STRING = "string"
    STRING_LIST = "string-list"
    CHOICE = "choice"
    MULTI_CHOICE = "multi-choice"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"


class _NoDefault:
    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_DEFAULT"


NO_DEFAULT = _NoDefault()


@dataclass(frozen=True, slots=True)
class LicensePoolVariable:
    """One typed field that the shared collector prompts for and stores."""

    name: str
    type: LicensePoolVariableType
    description: str
    choices: tuple[str, ...] = ()
    default: Any = NO_DEFAULT
    optional: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or _VARIABLE_NAME.fullmatch(self.name) is None
        ):
            raise LicensePoolMetadataError(
                "license-pool variable names must be identifiers containing only letters, numbers, '_', '.', or '-'"
            )
        if not isinstance(self.description, str) or not self.description.strip():
            raise LicensePoolMetadataError(
                f"license-pool variable {self.name!r} needs a prompt description"
            )
        if type(self.optional) is not bool:
            raise LicensePoolMetadataError(
                f"license-pool variable {self.name!r} optional must be a boolean"
            )
        try:
            variable_type = LicensePoolVariableType(self.type)
        except (TypeError, ValueError) as error:
            raise LicensePoolMetadataError(
                f"license-pool variable {self.name!r} has an unsupported type"
            ) from error
        object.__setattr__(self, "type", variable_type)

        if not isinstance(self.choices, (tuple, list)) or any(
            not isinstance(choice, str) or not choice for choice in self.choices
        ):
            raise LicensePoolMetadataError(
                f"license-pool variable {self.name!r} choices must be nonempty strings"
            )
        choices = tuple(self.choices)
        if len(set(choices)) != len(choices):
            raise LicensePoolMetadataError(
                f"license-pool variable {self.name!r} choices must be unique"
            )
        object.__setattr__(self, "choices", choices)
        requires_choices = variable_type in {
            LicensePoolVariableType.CHOICE,
            LicensePoolVariableType.MULTI_CHOICE,
        }
        if requires_choices and not choices:
            raise LicensePoolMetadataError(
                f"license-pool variable {self.name!r} needs at least one choice"
            )
        if not requires_choices and choices:
            raise LicensePoolMetadataError(
                f"license-pool variable {self.name!r} cannot declare choices for type {variable_type.value!r}"
            )
        if self.default is not NO_DEFAULT:
            normalized = _normalize_variable_value(self, self.default, from_text=False)
            object.__setattr__(self, "default", normalized)


def _parse_string_list(value: str) -> list[str]:
    """Split on ';', with ';;' representing a literal semicolon."""

    if value == "":
        return []
    result: list[str] = []
    item: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != ";":
            item.append(value[index])
            index += 1
        elif index + 1 < len(value) and value[index + 1] == ";":
            item.append(";")
            index += 2
        else:
            result.append("".join(item))
            item.clear()
            index += 1
    result.append("".join(item))
    return result


def _normalize_variable_value(
    variable: LicensePoolVariable,
    value: Any,
    *,
    from_text: bool,
) -> Any:
    variable_type = variable.type
    if variable_type is LicensePoolVariableType.STRING:
        if isinstance(value, str):
            return value
    elif variable_type is LicensePoolVariableType.STRING_LIST:
        if from_text and isinstance(value, str):
            return _parse_string_list(value)
        if isinstance(value, (tuple, list)) and all(
            isinstance(item, str) for item in value
        ):
            return tuple(value)
    elif variable_type is LicensePoolVariableType.CHOICE:
        if isinstance(value, str):
            candidate = value.strip() if from_text else value
            if candidate in variable.choices:
                return candidate
    elif variable_type is LicensePoolVariableType.MULTI_CHOICE:
        if from_text and isinstance(value, str):
            candidates = [item.strip() for item in _parse_string_list(value)]
        elif isinstance(value, (tuple, list)) and all(
            isinstance(item, str) for item in value
        ):
            candidates = list(value)
        else:
            candidates = []
            value = NO_DEFAULT
        if (
            value is not NO_DEFAULT
            and len(set(candidates)) == len(candidates)
            and all(item in variable.choices for item in candidates)
        ):
            return tuple(candidates)
    elif variable_type is LicensePoolVariableType.BOOLEAN:
        if from_text and isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "yes", "y", "1"}:
                return True
            if normalized in {"false", "no", "n", "0"}:
                return False
        elif type(value) is bool:
            return value
    elif variable_type is LicensePoolVariableType.INTEGER:
        if from_text and isinstance(value, str):
            normalized = value.strip()
            if re.fullmatch(r"[+-]?[0-9]+", normalized):
                return int(normalized)
        elif type(value) is int:
            return value
    elif variable_type is LicensePoolVariableType.FLOAT:
        if from_text and isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                pass
            else:
                if math.isfinite(number):
                    return number
        elif type(value) in {int, float}:
            number = float(value)
            if math.isfinite(number):
                return number

    if variable_type is LicensePoolVariableType.CHOICE:
        expected = "one of " + ", ".join(repr(item) for item in variable.choices)
    elif variable_type is LicensePoolVariableType.MULTI_CHOICE:
        expected = "a list containing only " + ", ".join(
            repr(item) for item in variable.choices
        )
    else:
        expected = variable_type.value
    raise LicensePoolMetadataError(
        f"license-pool variable {variable.name!r} must be {expected}"
    )


def parse_license_pool_variable_value(variable: LicensePoolVariable, value: str) -> Any:
    """Parse a command-line or prompt value according to its declaration."""

    if not isinstance(value, str):
        raise LicensePoolMetadataError(
            f"license-pool variable {variable.name!r} must be supplied as text"
        )
    return _normalize_variable_value(variable, value, from_text=True)


def validate_license_pool_variable_value(
    variable: LicensePoolVariable, value: Any
) -> Any:
    """Validate and normalize a typed value supplied by a contributor."""

    return _normalize_variable_value(variable, value, from_text=False)


def format_license_pool_variable_value(
    variable: LicensePoolVariable, value: Any
) -> str:
    """Format a typed value for a prompt default or a CLI override."""

    normalized = _normalize_variable_value(variable, value, from_text=False)
    if variable.type in {
        LicensePoolVariableType.STRING_LIST,
        LicensePoolVariableType.MULTI_CHOICE,
    }:
        return ";".join(item.replace(";", ";;") for item in normalized)
    if variable.type is LicensePoolVariableType.BOOLEAN:
        return "true" if normalized else "false"
    return str(normalized)


def metadata_variables_for(
    contributor: LicensePoolMetadataContributor,
) -> tuple[LicensePoolVariable, ...]:
    """Read and validate a contributor's optional variable declarations."""

    declarations = getattr(contributor, "metadata_variables", ())
    if callable(declarations):
        declarations = declarations()
    if not isinstance(declarations, (tuple, list)):
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor.contributor_id!r} metadata_variables must be a sequence"
        )
    result = tuple(declarations)
    if any(not isinstance(item, LicensePoolVariable) for item in result):
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor.contributor_id!r} has an invalid variable declaration"
        )
    names = [item.name for item in result]
    if len(set(names)) != len(names):
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor.contributor_id!r} declares duplicate variable names"
        )
    return result


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PoolMetadata:
    """Namespaced metadata plus any pre-API flat manifest values."""

    exists: bool
    legacy_flat: bool
    contributors: Mapping[str, Mapping[str, Any]]
    legacy: Mapping[str, Any]

    def for_contributor(self, contributor_id: str) -> Mapping[str, Any]:
        return cast(
            Mapping[str, Any],
            _freeze_json(self.contributors.get(contributor_id, {})),
        )

    def merged(self, contributions: Mapping[str, Mapping[str, Any]]) -> PoolMetadata:
        contributors = {
            contributor_id: {key: _thaw_json(value) for key, value in fields.items()}
            for contributor_id, fields in self.contributors.items()
        }
        for contributor_id, fields in contributions.items():
            current = contributors.setdefault(contributor_id, {})
            for key, value in fields.items():
                if value is None:
                    current.pop(key, None)
                else:
                    current[key] = value
            if not current:
                contributors.pop(contributor_id, None)
        result = PoolMetadata(
            exists=self.exists or bool(contributions),
            legacy_flat=False,
            contributors=MappingProxyType(
                {
                    contributor_id: _freeze_json(fields)
                    for contributor_id, fields in contributors.items()
                }
            ),
            legacy=_freeze_json(self.legacy),
        )
        result.to_document()  # Validate JSON compatibility before publication.
        return result

    def to_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "version": POOL_METADATA_VERSION,
            "contributors": {
                contributor_id: {
                    key: _thaw_json(value) for key, value in fields.items()
                }
                for contributor_id, fields in self.contributors.items()
            },
        }
        if self.legacy:
            document["legacy"] = _thaw_json(self.legacy)
        try:
            json.dumps(document, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise LicensePoolMetadataError(
                "license-pool metadata must contain only JSON-compatible values"
            ) from error
        return document


@dataclass(frozen=True, slots=True)
class LicensePoolMetadataContext:
    """Read-only inputs provided to one metadata contributor.

    `variable_values` contains CLI overrides while the collector resolves
    contributor-supplied values, then contains all resolved values when it
    calls `collect_metadata()`.
    """

    pool: Path
    kind: str
    kind_explicit: bool
    arguments: tuple[str, ...]
    environment: Mapping[str, str]
    cwd: Path
    existing: Mapping[str, Any]
    legacy: Mapping[str, Any]
    metadata_file_exists: bool
    update: bool
    interactive: bool
    variable_values: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


@runtime_checkable
class LicensePoolMetadataContributor(Protocol):
    """Contribute one namespaced update for an `init-license-pool` request.

    Implementations may also expose `metadata_variables`, a sequence of
    `LicensePoolVariable` declarations collected by the shared plugin before
    `collect_metadata()` runs, and `resolve_variable_values()` to provide
    typed values that take precedence over stored values and prompts.
    """

    contributor_id: str

    def collect_metadata(
        self, context: LicensePoolMetadataContext
    ) -> Mapping[str, Any] | None: ...


@runtime_checkable
class LicensePoolMetadataVariableResolver(Protocol):
    """Optional contributor capability for explicit typed variable values."""

    def resolve_variable_values(
        self, context: LicensePoolMetadataContext
    ) -> Mapping[str, Any]: ...


def load_pool_metadata(pool: Path | str) -> PoolMetadata:
    """Read a versioned metadata document or expose a legacy flat object."""

    path = Path(pool) / POOL_METADATA_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return PoolMetadata(False, False, MappingProxyType({}), MappingProxyType({}))
    except OSError as error:
        raise LicensePoolMetadataError(f"cannot read {path}: {error}") from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LicensePoolMetadataError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise LicensePoolMetadataError(f"{path} must contain a JSON object")
    if "version" not in document:
        return PoolMetadata(
            True,
            True,
            MappingProxyType({}),
            _freeze_json(document),
        )
    if (
        type(document.get("version")) is not int
        or document.get("version") != POOL_METADATA_VERSION
    ):
        raise LicensePoolMetadataError(
            f"{path} has unsupported metadata version {document.get('version')!r}"
        )
    unknown = set(document) - {"version", "contributors", "legacy"}
    if unknown:
        raise LicensePoolMetadataError(
            f"{path} has unknown top-level keys: {', '.join(sorted(unknown))}"
        )
    contributors = document.get("contributors", {})
    legacy = document.get("legacy", {})
    if not isinstance(contributors, dict) or not isinstance(legacy, dict):
        raise LicensePoolMetadataError(
            f"{path} contributors and legacy fields must be JSON objects"
        )
    if any(
        not isinstance(contributor_id, str)
        or not isinstance(fields, dict)
        or any(not isinstance(key, str) for key in fields)
        for contributor_id, fields in contributors.items()
    ):
        raise LicensePoolMetadataError(
            f"{path} contributor metadata must map IDs to string-keyed objects"
        )
    return PoolMetadata(
        True,
        False,
        MappingProxyType(
            {
                contributor_id: _freeze_json(fields)
                for contributor_id, fields in contributors.items()
            }
        ),
        _freeze_json(legacy),
    )


def validate_contribution(
    contributor_id: str, value: Mapping[str, Any] | None
) -> Mapping[str, Any] | None:
    """Check a contributor result before the collector merges it."""

    if value is None:
        return None
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor_id!r} must return a string-keyed mapping"
        )
    normalized = {key: _thaw_json(item) for key, item in value.items()}
    try:
        json.dumps(normalized, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise LicensePoolMetadataError(
            f"license-pool metadata contributor {contributor_id!r} returned non-JSON metadata"
        ) from error
    return cast(Mapping[str, Any], _freeze_json(normalized))


def discover_metadata_contributors() -> tuple[LicensePoolMetadataContributor, ...]:
    """Load installed metadata contributors in stable entry-point order."""

    found: list[LicensePoolMetadataContributor] = []
    for entry in sorted(
        importlib.metadata.entry_points(group=POOL_METADATA_CONTRIBUTOR_GROUP),
        key=lambda item: item.name,
    ):
        if _CONTRIBUTOR_ID.fullmatch(entry.name) is None:
            raise LicensePoolMetadataError(
                f"license-pool metadata contributor ID {entry.name!r} is invalid"
            )
        try:
            candidate = entry.load()
            value = candidate() if isinstance(candidate, type) else candidate
        except Exception as error:
            raise LicensePoolMetadataError(
                f"cannot load license-pool metadata contributor {entry.name!r}: {error}"
            ) from error
        if not isinstance(value, LicensePoolMetadataContributor):
            raise LicensePoolMetadataError(
                f"license-pool metadata contributor {entry.name!r} has an invalid contract"
            )
        if entry.name != value.contributor_id:
            raise LicensePoolMetadataError(
                f"license-pool metadata contributor entry point {entry.name!r} does not match {value.contributor_id!r}"
            )
        found.append(value)
    return tuple(found)
