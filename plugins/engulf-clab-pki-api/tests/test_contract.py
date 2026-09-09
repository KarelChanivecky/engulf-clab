from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath

from engulf_clab_pki_api import (
    AuthorityClassification,
    NodePkiProjection,
    PkiNodeProjections,
    ProjectedFile,
    PublicAuthorityProjection,
)


def artifact(name: str = "certificate.pem") -> ProjectedFile:
    return ProjectedFile(
        Path("/state/view") / name,
        PurePosixPath("/mnt/pki") / name,
    )


class ProjectionContractTest(unittest.TestCase):
    def test_projection_is_immutable_and_path_correspondence_is_validated(self) -> None:
        public = PublicAuthorityProjection(
            "global",
            "root",
            "default",
            "a" * 64,
            AuthorityClassification.TRUST_ANCHOR,
            artifact(),
            artifact("chain.pem"),
            artifact("full-chain.pem"),
        )
        node = NodePkiProjection(
            "fgt",
            "fortinet_fortigate",
            Path("/state/view"),
            PurePosixPath("/mnt/pki"),
            (public,),
        )
        projections = PkiNodeProjections((node,))
        self.assertEqual(projections.nodes[0].public_authorities[0].name, "root")
        with self.assertRaises(AttributeError):
            projections.nodes = ()  # type: ignore[misc]

    def test_rejects_escaped_and_mismatched_paths(self) -> None:
        with self.assertRaises(ValueError):
            ProjectedFile(Path("/state/view/cert.pem"), PurePosixPath("/mnt/pki/bad;path"))
        with self.assertRaisesRegex(ValueError, "do not correspond"):
            NodePkiProjection(
                "fgt",
                "fortinet_fortigate",
                Path("/state/view"),
                PurePosixPath("/mnt/pki"),
                (),
                (),
                (),
            ).__class__(
                "fgt",
                "fortinet_fortigate",
                Path("/state/view"),
                PurePosixPath("/mnt/pki"),
                (
                    PublicAuthorityProjection(
                        "global",
                        "root",
                        "default",
                        "b" * 64,
                        AuthorityClassification.TRUST_ANCHOR,
                        ProjectedFile(Path("/state/view/a.pem"), PurePosixPath("/mnt/pki/b.pem")),
                        artifact("chain.pem"),
                        artifact("full-chain.pem"),
                    ),
                ),
            )

    def test_rejects_duplicate_or_unsorted_nodes(self) -> None:
        first = NodePkiProjection("z", "linux", Path("/state/z"), PurePosixPath("/mnt/pki"))
        second = NodePkiProjection("a", "linux", Path("/state/a"), PurePosixPath("/mnt/pki"))
        with self.assertRaisesRegex(ValueError, "sorted"):
            PkiNodeProjections((first, second))
        with self.assertRaisesRegex(ValueError, "unique"):
            PkiNodeProjections((first, first))

    def test_accepts_namespaced_bridge_node_name_but_rejects_path_components(self) -> None:
        projection = NodePkiProjection(
            "client-net|segments",
            "bridge",
            Path("/state/client-net|segments"),
            PurePosixPath("/mnt/pki"),
        )
        self.assertEqual(projection.node_name, "client-net|segments")
        for invalid in ("", ".", "..", "parent/child", "bad:name", "bad;name"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "path-safe"):
                NodePkiProjection(invalid, "linux", Path("/state/view"), PurePosixPath("/mnt/pki"))
