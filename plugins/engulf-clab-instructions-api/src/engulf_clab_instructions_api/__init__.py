"""Shared post-deployment instruction contribution contract."""

from .contract import (
    INSTRUCTION_CONTEXTS,
    INSTRUCTIONS_CONTEXT,
    DeploymentInstruction,
    instructions,
    record_instruction,
)

__all__ = [
    "INSTRUCTIONS_CONTEXT",
    "INSTRUCTION_CONTEXTS",
    "DeploymentInstruction",
    "instructions",
    "record_instruction",
]
