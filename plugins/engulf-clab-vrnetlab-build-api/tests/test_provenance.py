from __future__ import annotations

import unittest
from unittest.mock import Mock

from engulf_clab_vrnetlab_build_api import (
    VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
    VrnetlabSourceProvenance,
    VrnetlabSourceProvenanceSnapshot,
    publish_vrnetlab_source_provenance,
)


class VrnetlabSourceProvenanceTest(unittest.TestCase):
    def test_snapshot_keeps_one_source_record_per_node(self) -> None:
        first = VrnetlabSourceProvenance(
            node_name="router-1",
            builder_type="vendor/router",
            source_provider_id="org.example.images.static",
            source_sha256="a" * 64,
        )
        second = VrnetlabSourceProvenance(
            node_name="router-2",
            builder_type="vendor/router",
            source_provider_id="org.example.images.remote",
            source_sha256="b" * 64,
        )
        snapshot = VrnetlabSourceProvenanceSnapshot((first, second))

        self.assertEqual(snapshot.source_for("router-1"), first)
        self.assertEqual(snapshot.source_for("router-2"), second)
        self.assertIsNone(snapshot.source_for("router-3"))
        self.assertEqual(snapshot.sources, (first, second))
        self.assertFalse(hasattr(first, "image"))

    def test_snapshot_rejects_two_selected_sources_for_one_node(self) -> None:
        first = VrnetlabSourceProvenance(
            node_name="router-1",
            builder_type="vendor/router",
            source_provider_id="org.example.images.static",
            source_sha256="a" * 64,
        )
        second = VrnetlabSourceProvenance(
            node_name="router-1",
            builder_type="vendor/router",
            source_provider_id="org.example.images.remote",
            source_sha256="b" * 64,
        )

        with self.assertRaisesRegex(ValueError, "one record per node"):
            VrnetlabSourceProvenanceSnapshot((first, second))

    def test_source_records_require_a_sha256_and_global_provider_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            VrnetlabSourceProvenance(
                node_name="router-1",
                builder_type="vendor/router",
                source_provider_id="org.example.images.static",
                source_sha256="not-a-digest",
            )
        with self.assertRaises(ValueError):
            VrnetlabSourceProvenance(
                node_name="router-1",
                builder_type="vendor/router",
                source_provider_id="static",
                source_sha256="a" * 64,
            )

    def test_source_provenance_context_can_remain_unread(self) -> None:
        snapshot = VrnetlabSourceProvenanceSnapshot()
        api = Mock()

        publish_vrnetlab_source_provenance(api, snapshot)

        api.set_context.assert_called_once_with(
            VRNETLAB_SOURCE_PROVENANCE_CONTEXT,
            snapshot,
            allow_unused=True,
        )


if __name__ == "__main__":
    unittest.main()
