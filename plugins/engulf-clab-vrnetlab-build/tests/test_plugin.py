from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

from engulf_clab_lab_parser import RUNTIME_TOPOLOGY_CONTEXT, TopologySession
from engulf_clab_vrnetlab_build_api import (
    VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
    VrnetlabSourceProvenance,
    VrnetlabSourceProvenanceSnapshot,
)
from engulf_docker_image_api import DOCKER_IMAGE_PROVENANCE_CONTEXT
from engulf_executable_wrapper_api import CallMode, OutcomeKind

from engulf_clab_vrnetlab_build.plugin import VrnetlabBuilderPlugin
from engulf_clab_vrnetlab_build.provenance import STATE_BASENAME


class MemoryStateStore:
    def __init__(self) -> None:
        self.content: dict[str, str] = {}

    def exists(self, basename: str) -> bool:
        return basename in self.content

    def read_text(self, basename: str) -> str:
        return self.content[basename]

    def write_text(self, basename: str, content: str) -> None:
        self.content[basename] = content

    @contextmanager
    def transaction(self, *, timeout: float | None = None) -> Iterator[MemoryStateStore]:
        del timeout
        yield self


class VrnetlabBuilderPluginTest(unittest.TestCase):
    def test_source_registry_is_separate_from_docker_image_registry(self) -> None:
        self.assertIn(
            VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
            VrnetlabBuilderPlugin.context_writes,
        )
        self.assertNotIn(
            DOCKER_IMAGE_PROVENANCE_CONTEXT,
            VrnetlabBuilderPlugin.context_reads | VrnetlabBuilderPlugin.context_writes,
        )

    def test_before_goal_restores_source_provenance_into_its_own_context(self) -> None:
        expected = VrnetlabSourceProvenance(
            node_name="router-1",
            builder_type="vendor/router",
            source_provider_id="org.example.images.static",
            source_sha256="a" * 64,
        )
        state = MemoryStateStore()
        state.content[STATE_BASENAME] = json.dumps(
            {
                "version": 1,
                "sources": [
                    {
                        "node_name": expected.node_name,
                        "builder_type": expected.builder_type,
                        "source_provider_id": expected.source_provider_id,
                        "source_sha256": expected.source_sha256,
                    }
                ],
            }
        )
        contexts: dict[str, object] = {}
        api = Mock()
        api.state.return_value = state
        api.get_context.side_effect = lambda context_id, default=None: contexts.get(
            context_id, default
        )
        api.set_context.side_effect = lambda context_id, value, **_kwargs: contexts.__setitem__(
            context_id, value
        )

        result = VrnetlabBuilderPlugin().before_goal(Mock(), api)

        self.assertIsNone(result)
        self.assertEqual(
            contexts[VRNETLAB_SOURCE_PROVENANCE_CONTEXT],
            VrnetlabSourceProvenanceSnapshot((expected,)),
        )
        api.set_context.assert_any_call(
            VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
            VrnetlabSourceProvenanceSnapshot((expected,)),
            allow_unused=True,
        )

    def test_after_call_persists_only_source_registry_fields(self) -> None:
        source = VrnetlabSourceProvenance(
            node_name="router-1",
            builder_type="vendor/router",
            source_provider_id="org.example.images.static",
            source_sha256="b" * 64,
        )
        snapshot = VrnetlabSourceProvenanceSnapshot((source,))
        state = MemoryStateStore()
        api = Mock()
        api.state.return_value = state
        api.get_context.side_effect = lambda _context_id, default=None: snapshot
        event = Mock(mode=CallMode.NORMAL, wrapper_args=("deploy",))

        VrnetlabBuilderPlugin().after_call(event, api)

        document = json.loads(state.content[STATE_BASENAME])
        self.assertEqual(
            document,
            {
                "version": 1,
                "sources": [
                    {
                        "node_name": "router-1",
                        "builder_type": "vendor/router",
                        "source_provider_id": "org.example.images.static",
                        "source_sha256": "b" * 64,
                    }
                ],
            },
        )
        self.assertNotIn("image", document["sources"][0])
        self.assertNotIn("source_path", document["sources"][0])

    def test_single_lab_inspect_reports_vrnetlab_source_provenance(self) -> None:
        source = VrnetlabSourceProvenance(
            node_name="router-1",
            builder_type="vendor/router",
            source_provider_id="org.example.images.static",
            source_sha256="c" * 64,
        )
        contexts = {
            RUNTIME_TOPOLOGY_CONTEXT: TopologySession(
                Path("lab.clab.yml"),
                {"topology": {"nodes": {"router-1": {"image": "router:1"}}}},
            ),
            VRNETLAB_SOURCE_PROVENANCE_CONTEXT: VrnetlabSourceProvenanceSnapshot(
                (source,)
            ),
        }
        api = Mock()
        api.get_context.side_effect = lambda key, default=None: contexts.get(key, default)
        event = Mock(
            mode=CallMode.NORMAL,
            wrapper_args=("inspect", "-t", "lab.clab.yml"),
            effective_args=("inspect", "-t", "lab.clab.yml"),
            outcome=Mock(kind=OutcomeKind.COMPLETED, exit_code=0),
        )

        VrnetlabBuilderPlugin().after_call(event, api)

        api.logger.info.assert_any_call("vrnetlab image source provenance:")
        api.logger.info.assert_any_call(
            "  node %s image=%s: builder=%s provider=%s source_sha256=%s",
            "router-1",
            "router:1",
            "vendor/router",
            "org.example.images.static",
            "c" * 64,
        )


if __name__ == "__main__":
    unittest.main()
