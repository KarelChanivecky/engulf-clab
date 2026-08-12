"""Callback-scoped logging helpers for image build operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from engulf_api import PluginLogger

_logger: ContextVar[PluginLogger | None] = ContextVar("logger", default=None)


@contextmanager
def use_logger(logger: PluginLogger) -> Iterator[None]:
    """Make a callback-bound plugin logger available to helper functions."""
    token = _logger.set(logger)
    try:
        yield
    finally:
        _logger.reset(token)


def info(message: str) -> None:
    if logger := _logger.get():
        logger.info(message)
