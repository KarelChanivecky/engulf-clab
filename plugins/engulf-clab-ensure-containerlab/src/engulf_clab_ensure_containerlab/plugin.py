from __future__ import annotations

import os

from engulf_api import InvocationAPI, StateScope
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    BeforeCallEvent,
    CallContribution,
    ExecutableWrapperPlugin,
    HelpAPI,
    PreparedCallEvent,
)

from .containerlab import ensure_binary
from .contract import CONTAINERLAB_REPOSITORY_LEASE, ENSURE_CONTAINERLAB_PLUGIN_ID
from .errors import EnsureContainerlabError
from .logging import use_logger


class EnsureContainerlabPlugin(ExecutableWrapperPlugin):
    """Provision a binary only when the standard wrapper executable needs it."""

    plugin_id = ENSURE_CONTAINERLAB_PLUGIN_ID
    # Run last in prepare and cleanup so a temporary PATH change cannot affect
    # other plugin callbacks and is restored after their finalization.
    priority = 0

    def __init__(self) -> None:
        self._original_path: str | None = None

    def help(self, api: HelpAPI) -> str:
        api.logger.debug("rendering Containerlab provisioning help")
        return (
            "  CONTAINERLAB_BIN   Use an executable Containerlab binary\n"
            "  CONTAINERLAB_DIR   Use or build a Containerlab source checkout\n"
            "  CONTAINERLAB_REPO  Override the managed checkout clone source"
        )

    def analyze_call(
        self,
        event: BeforeCallEvent,
        api: InvocationAPI,
    ) -> CallContribution | None:
        return None

    def prepare_call(self, event: PreparedCallEvent, api: InvocationAPI) -> None:
        if event.binary != "containerlab":
            return
        try:
            with use_logger(api.logger), api.lease(CONTAINERLAB_REPOSITORY_LEASE):
                binary = ensure_binary(api.state(StateScope.USER), os.environ)
            self._original_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{binary.parent}{os.pathsep}{self._original_path}"
        except (EnsureContainerlabError, OSError) as error:
            api.logger.error("%s", error)
            raise

    def after_call(self, event: AfterCallEvent, api: InvocationAPI) -> None:
        if self._original_path is not None:
            os.environ["PATH"] = self._original_path
            self._original_path = None
