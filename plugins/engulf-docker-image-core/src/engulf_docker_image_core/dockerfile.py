from __future__ import annotations

import re
import shlex
from collections.abc import Mapping

from engulf_docker_image_api import DockerfileRecipe, ImageRequirement

from .errors import DockerfileAnalysisError

_ARG_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VARIABLE = re.compile(
    r"\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*)|"
    r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?:(?P<operator>:-|-)(?P<default>[^}]*))?\}"
)


def dockerfile_requirements(recipe: DockerfileRecipe) -> tuple[ImageRequirement, ...]:
    """Return statically discoverable external FROM and COPY sources in file order."""
    try:
        source = recipe.dockerfile.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise DockerfileAnalysisError(
            f"cannot read Dockerfile {recipe.dockerfile}: {error}"
        ) from error

    arguments: dict[str, str | None] = {}
    arguments.update(dict(recipe.build_args))
    aliases: set[str] = set()
    requirements: list[ImageRequirement] = []
    seen: set[str] = set()
    found_from = False

    for line_number, line in _logical_lines(source):
        fields = line.split(None, 1)
        if len(fields) != 2:
            continue
        instruction, body = fields
        instruction = instruction.upper()
        body = body.strip()
        if instruction == "ARG" and not found_from:
            name, equals, default = body.partition("=")
            name = name.strip()
            if _ARG_NAME.fullmatch(name) is not None and name not in arguments:
                arguments[name] = default if equals else None
            continue
        if instruction == "COPY":
            try:
                tokens = shlex.split(body, posix=True)
            except ValueError as error:
                raise DockerfileAnalysisError(
                    f"invalid COPY instruction in {recipe.dockerfile}:{line_number}: {error}"
                ) from error
            copy_source: str | None = None
            index = 0
            while index < len(tokens) and tokens[index].startswith("--"):
                option = tokens[index]
                if option.startswith("--from="):
                    copy_source = option.partition("=")[2]
                elif option == "--from":
                    index += 1
                    if index >= len(tokens):
                        raise DockerfileAnalysisError(
                            f"missing COPY --from value at {recipe.dockerfile}:{line_number}"
                        )
                    copy_source = tokens[index]
                index += 1
            if copy_source is None:
                continue
            token = _expanded(copy_source, arguments)
            if token is None:
                raise DockerfileAnalysisError(
                    f"cannot provision dynamic COPY --from image at "
                    f"{recipe.dockerfile}:{line_number}"
                )
            if token.lower() not in aliases and token.lower() != "scratch" and token not in seen:
                seen.add(token)
                requirements.append(
                    ImageRequirement(token, origin=f"{recipe.dockerfile}:{line_number}")
                )
            continue
        if instruction != "FROM":
            continue
        found_from = True
        try:
            tokens = shlex.split(body, posix=True)
        except ValueError as error:
            raise DockerfileAnalysisError(
                f"invalid FROM instruction in {recipe.dockerfile}:{line_number}: {error}"
            ) from error
        while tokens and tokens[0].startswith("--"):
            tokens.pop(0)
        if not tokens:
            raise DockerfileAnalysisError(
                f"missing image in FROM instruction at {recipe.dockerfile}:{line_number}"
            )
        token = _expanded(tokens[0], arguments)
        stage_reference = token is not None and token.lower() in aliases
        if len(tokens) >= 3 and tokens[1].upper() == "AS":
            aliases.add(tokens[2].lower())
        if token is None:
            raise DockerfileAnalysisError(
                f"cannot provision dynamic FROM image at {recipe.dockerfile}:{line_number}"
            )
        if token.lower() == "scratch" or stage_reference:
            continue
        if token not in seen:
            seen.add(token)
            requirements.append(
                ImageRequirement(token, origin=f"{recipe.dockerfile}:{line_number}")
            )
    return tuple(requirements)


def _logical_lines(source: str) -> tuple[tuple[int, str], ...]:
    result: list[tuple[int, str]] = []
    parts: list[str] = []
    start = 0
    for line_number, raw in enumerate(source.splitlines(), 1):
        stripped = raw.strip()
        if not parts and (not stripped or stripped.startswith("#")):
            continue
        if not parts:
            start = line_number
        continued = stripped.endswith("\\")
        parts.append(stripped[:-1].rstrip() if continued else stripped)
        if not continued:
            logical = " ".join(parts).strip()
            if logical:
                result.append((start, logical))
            parts = []
    if parts:
        result.append((start, " ".join(parts).strip()))
    return tuple(result)


def _expanded(value: str, arguments: Mapping[str, str | None]) -> str | None:
    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group("plain") or match.group("braced")
        current = arguments.get(name)
        operator = match.group("operator")
        if current is not None and (current or operator != ":-"):
            return current
        default = match.group("default")
        if operator is not None and default is not None:
            return default
        unresolved = True
        return match.group(0)

    expanded = _VARIABLE.sub(replace, value)
    if unresolved or "$" in expanded:
        return None
    return expanded
