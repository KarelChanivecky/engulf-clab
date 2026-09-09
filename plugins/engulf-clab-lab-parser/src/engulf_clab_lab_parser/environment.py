from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

# Owner-private variables a lab may resolve its topology from. These are read
# only to expand the topology; unlike Containerlab's `env-files:` they never
# become node environment, so nothing here reaches a container unless the
# topology references it explicitly.
ENV_FILE_SUFFIX = ".env"
ENV_FILE_OVERRIDE = "ECLAB_ENV_FILE"
_TOPOLOGY_SUFFIXES = (".clab.yml", ".clab.yaml")


class EnvironmentExpansionError(ValueError):
    pass


class EnvFileError(ValueError):
    pass


def expand_environment(source: str, environment: Mapping[str, str]) -> str:
    """Expand Containerlab's supported shell-style environment expressions."""
    output: list[str] = []
    index = 0
    while index < len(source):
        if source[index] != "$":
            output.append(source[index])
            index += 1
            continue

        if index + 1 >= len(source):
            output.append("$")
            break
        following = source[index + 1]
        if following == "$":
            output.append("$")
            index += 2
            continue
        if following == "{":
            closing = source.find("}", index + 2)
            if closing < 0 or "\n" in source[index + 2 : closing]:
                raise EnvironmentExpansionError("closing brace expected")
            expression = source[index + 2 : closing]
            output.append(_expand_braced(expression, environment))
            index = closing + 1
            continue
        if not _is_variable_character(following) or following.isdigit():
            output.append("$")
            index += 1
            continue

        end = index + 2
        while end < len(source) and _is_variable_character(source[end]):
            end += 1
        name = source[index + 1 : end]
        output.append(_direct_value(name, environment))
        index = end
    return "".join(output)


def _expand_braced(expression: str, environment: Mapping[str, str]) -> str:
    name_end = 0
    while name_end < len(expression) and _is_variable_character(expression[name_end]):
        name_end += 1
    name = expression[:name_end]
    if not name or name[0].isdigit():
        return "${" + expression + "}"

    remainder = expression[name_end:]
    if not remainder:
        return _direct_value(name, environment)

    operator = next(
        (candidate for candidate in (":-", ":=", ":+", "-", "=", "+") if remainder.startswith(candidate)),
        None,
    )
    if operator is None:
        raise EnvironmentExpansionError(f"unsupported environment expression ${{{expression}}}")
    default = remainder[len(operator) :]
    is_set = name in environment
    value = environment.get(name, "")

    if operator in ("-", "="):
        return _direct_value(name, environment) if is_set else expand_environment(default, environment)
    if operator in (":-", ":="):
        return value if value else expand_environment(default, environment)
    if operator in ("+", ":+"):
        return expand_environment(default, environment) if is_set else ""
    raise AssertionError(f"unhandled environment operator {operator}")


def _direct_value(name: str, environment: Mapping[str, str]) -> str:
    value = environment.get(name, "")
    return value if value else f"${name}"


def _is_variable_character(value: str) -> bool:
    return value == "_" or value.isalnum()


def env_file_for_topology(topology: Path) -> Path:
    """Return the private env file a topology may sit beside.

    The stem is taken from the filename rather than the topology's `name:`
    field: the file has to be found before the document can be expanded, and
    the two routinely differ (`all-features.clab.yml` declaring
    `name: eclab-all-features`).
    """
    name = topology.name
    for suffix in _TOPOLOGY_SUFFIXES:
        if name.endswith(suffix):
            return topology.with_name(name[: -len(suffix)] + ENV_FILE_SUFFIX)
    return topology.with_name(topology.stem + ENV_FILE_SUFFIX)


def parse_env_file(source: str) -> dict[str, str]:
    """Parse the assignment subset of dotenv syntax that eclab accepts.

    Blank lines and `#` comments are skipped, a leading `export ` is allowed,
    and values may be single-quoted (literal), double-quoted (with `\\n`, `\\t`,
    `\\\\` and `\\"` unescaped), or bare (trailing ` #` comment stripped). Values
    are never interpolated against each other or the environment: an env file
    is data, and expansion belongs to the topology.
    """
    values: dict[str, str] = {}
    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not _is_variable_name(name):
            raise EnvFileError(f"line {number}: expected NAME=value, got {raw.strip()!r}")
        values[name] = _env_file_value(value.strip(), number)
    return values


def _is_variable_name(name: str) -> bool:
    return bool(name) and not name[0].isdigit() and all(map(_is_variable_character, name))


def _env_file_value(value: str, number: int) -> str:
    for quote in ("'", '"'):
        if value.startswith(quote):
            if len(value) < 2 or not value.endswith(quote):
                raise EnvFileError(f"line {number}: unterminated {quote} quoted value")
            inner = value[1:-1]
            return _unescape(inner) if quote == '"' else inner
    # A bare value ends at an unquoted comment, which needs leading whitespace
    # so that values such as api#1 keep their hash.
    head, separator, _ = value.partition(" #")
    return head.rstrip() if separator else value


def _unescape(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            following = value[index + 1]
            replacement = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(following)
            if replacement is not None:
                output.append(replacement)
                index += 2
                continue
        output.append(character)
        index += 1
    return "".join(output)


def topology_environment(
    topology: Path, environment: Mapping[str, str]
) -> Mapping[str, str]:
    """Layer a lab's private env file underneath the process environment.

    The process environment wins, so `FOO=x eclab deploy` still overrides the
    file. Files named through ENV_FILE_OVERRIDE replace the convention and must
    exist; the conventional sibling is optional and skipped when absent.
    """
    named = _override_paths(environment)
    if named is None:
        candidate = env_file_for_topology(topology)
        paths: Sequence[Path] = (candidate,) if candidate.is_file() else ()
    else:
        for path in named:
            if not path.is_file():
                raise EnvFileError(f"{ENV_FILE_OVERRIDE} entry does not exist: {path}")
        paths = named

    if not paths:
        return environment

    merged: dict[str, str] = {}
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            raise EnvFileError(f"could not read env file {path}: {error}") from error
        try:
            merged.update(parse_env_file(source))
        except EnvFileError as error:
            raise EnvFileError(f"{path}: {error}") from error
    merged.update(environment)
    return merged


def _override_paths(environment: Mapping[str, str]) -> tuple[Path, ...] | None:
    raw = environment.get(ENV_FILE_OVERRIDE)
    if raw is None or not raw.strip():
        return None
    return tuple(Path(entry).expanduser() for entry in raw.split(os.pathsep) if entry)
