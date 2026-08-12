from __future__ import annotations

from engulf_api import InvocationAPI
from engulf_executable_wrapper_api import (
    BeforeCallEvent,
    CallContribution,
    ExecutableWrapperPlugin,
    HelpAPI,
)


class FreezePlugin(ExecutableWrapperPlugin):
    """Advertise the freeze command while its CLI action remains side-effect free."""

    plugin_id = "engulf_clab.freeze"
    priority = 90

    def help(self, api: HelpAPI) -> str:
        del api
        return "  freeze -t TOPOLOGY --output ARCHIVE  Create a sanitized portable lab archive"

    def analyze_call(
        self, event: BeforeCallEvent, api: InvocationAPI
    ) -> CallContribution | None:
        del event, api
        return None
