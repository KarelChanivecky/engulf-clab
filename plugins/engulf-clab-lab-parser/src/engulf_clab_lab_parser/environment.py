from __future__ import annotations

from collections.abc import Mapping


class EnvironmentExpansionError(ValueError):
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
