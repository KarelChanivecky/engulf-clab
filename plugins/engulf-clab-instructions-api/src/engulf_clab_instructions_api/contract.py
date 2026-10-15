from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from engulf_api import InvocationAPI

INSTRUCTIONS_CONTEXT = "engulf_clab.instructions.entries"
INSTRUCTION_CONTEXTS = frozenset({INSTRUCTIONS_CONTEXT})


def _text(value: object, label: str, *, multiline: bool = False, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not empty and not value.strip():
        raise ValueError(f"{label} must not be empty")
    for character in value:
        codepoint = ord(character)
        if codepoint == 127 or (codepoint < 32 and character not in "\t\n"):
            raise ValueError(f"{label} must not contain terminal control characters")
        if not multiline and character in "\r\n":
            raise ValueError(f"{label} must be a single line")
    return value


@dataclass(frozen=True, slots=True)
class DeploymentInstruction:
    """One operator-facing follow-up shown after a successful deployment."""

    title: str
    text: str = ""
    commands: tuple[str, ...] = ()
    urls: tuple[str, ...] = ()
    node: str | None = None

    def __post_init__(self) -> None:
        _text(self.title, "instruction title")
        _text(self.text, "instruction text", multiline=True, empty=True)
        if type(self.commands) is not tuple:
            raise TypeError("commands must be a tuple of single-line strings")
        for command in self.commands:
            _text(command, "command")
        if type(self.urls) is not tuple:
            raise TypeError("urls must be a tuple of HTTP(S) URLs")
        for url in self.urls:
            _text(url, "URL")
            try:
                parsed = urlsplit(url)
            except ValueError as error:
                raise ValueError("URLs must be valid absolute HTTP(S) URLs") from error
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("URLs must be absolute HTTP(S) URLs without embedded credentials")
        if self.node is not None:
            _text(self.node, "node name")

        if not self.text.strip() and not self.commands and not self.urls:
            raise ValueError("an instruction must include text, commands, or URLs")


def instructions(api: InvocationAPI) -> tuple[DeploymentInstruction, ...]:
    """Return contributions already recorded for this invocation."""
    value = api.get_context(INSTRUCTIONS_CONTEXT, ())
    if type(value) is not tuple or any(
        not isinstance(item, DeploymentInstruction) for item in value
    ):
        raise RuntimeError("invalid deployment instruction registry")
    return value


def record_instruction(api: InvocationAPI, instruction: DeploymentInstruction) -> None:
    """Add one instruction to the invocation-scoped registry."""
    if not isinstance(instruction, DeploymentInstruction):
        raise TypeError("instruction must be a DeploymentInstruction")
    current = instructions(api)
    if instruction not in current:
        api.set_context(
            INSTRUCTIONS_CONTEXT,
            (*current, instruction),
            allow_unused=True,
        )
