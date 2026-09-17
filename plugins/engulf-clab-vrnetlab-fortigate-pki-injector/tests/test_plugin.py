from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import Mock

from engulf_api import InvocationAPI
from engulf_clab_lab_parser import TopologySession
from engulf_clab_pki_api import (
    AuthorityClassification,
    IssuedIdentityProjection,
    NodePkiProjection,
    PkiNodeProjections,
    ProjectedFile,
    PublicAuthorityProjection,
    RequestedAuthorityProjection,
)
from engulf_executable_wrapper_api import CallMode, PreparedCallEvent

from engulf_clab_vrnetlab_fortigate_pki_injector.plugin import (
    CA_CERTIFICATES,
    CRLS,
    LOCAL_CERTIFICATE_PASSWORD_FILES,
    LOCAL_CERTIFICATES,
    REMOTE_CERTIFICATES,
    FortigatePkiInjector,
    InjectorError,
)


class FortigatePkiInjectorTest(unittest.TestCase):
    def test_package_declares_parser_pki_writer_and_schema_ordering(self) -> None:
        package = Path(__file__).parents[1]
        metadata = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = metadata["project"]["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_vrnetlab_fortigate_pki_injector"
        ]
        self.assertEqual(
            dependencies,
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.pki": "preprocess=before; postprocess=none",
                "engulf_clab.lab_writer": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )

    def test_injects_canonical_ca_and_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projection = _projection(root, kind="fortinet_fortigate")
            session = _session(projection)
            _prepare(session, PkiNodeProjections((projection,)))
            environment = session.materialize()["topology"]["nodes"]["fgt"]["env"]
            self.assertEqual(
                environment[CA_CERTIFICATES],
                "root:/mnt/pki/authorities/effective/root/default/certificate.pem",
            )
            self.assertEqual(
                environment[LOCAL_CERTIFICATES],
                "root:/mnt/pki/private/authorities/global/root/default/private-key.pem:"
                "/mnt/pki/authorities/global/root/default/certificate.pem;"
                "tls:/mnt/pki/issued/fgt/tls/private-key.pem:"
                "/mnt/pki/issued/fgt/tls/certificate.pem",
            )
            self.assertNotIn(CRLS, environment)
            self.assertNotIn(LOCAL_CERTIFICATE_PASSWORD_FILES, environment)
            self.assertNotIn(REMOTE_CERTIFICATES, environment)

    def test_resolves_inherited_kind_bind_and_group_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projection = _projection(root, kind="fortinet_fortigate")
            bind = f"{projection.staged_view}:{projection.mount_target}:ro"
            session = TopologySession(
                Path("/tmp/lab.clab.yml"),
                {
                    "topology": {
                        "defaults": {"kind": projection.node_kind},
                        "kinds": {projection.node_kind: {"binds": [bind]}},
                        "nodes": {"fgt": {}},
                    }
                },
            )
            _prepare(session, PkiNodeProjections((projection,)))
            self.assertIn(
                CA_CERTIFICATES,
                session.materialize()["topology"]["nodes"]["fgt"]["env"],
            )

            collision_session = TopologySession(
                Path("/tmp/lab.clab.yml"),
                {
                    "topology": {
                        "defaults": {"kind": projection.node_kind},
                        "groups": {
                            "clients": {
                                "binds": [bind],
                                "env": {CRLS: "/manual/crl.pem"},
                            }
                        },
                        "nodes": {"fgt": {"group": "clients"}},
                    }
                },
            )
            with self.assertRaisesRegex(InjectorError, "topology group 'clients'"):
                _prepare(collision_session, PkiNodeProjections((projection,)))
            self.assertNotIn(
                "env", collision_session.materialize()["topology"]["nodes"]["fgt"]
            )

    def test_missing_pki_context_is_a_complete_noop(self) -> None:
        api = Mock(spec=InvocationAPI)
        api.get_context.return_value = None
        event = PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, {})
        FortigatePkiInjector().prepare_call(event, api)
        api.require_context.assert_not_called()

    def test_non_fortigate_projection_is_a_noop(self) -> None:
        projection = NodePkiProjection(
            "fgt", "linux", Path("/missing/view"), PurePosixPath("/mnt/pki")
        )
        session = _session(projection)
        _prepare(session, PkiNodeProjections((projection,)))
        self.assertNotIn("env", session.materialize()["topology"]["nodes"]["fgt"])

    def test_projection_for_removed_build_only_node_is_a_noop(self) -> None:
        projection = NodePkiProjection(
            "image-build", "linux", Path("/missing/view"), PurePosixPath("/mnt/pki")
        )
        session = TopologySession(
            Path("/tmp/lab.clab.yml"), {"topology": {"nodes": {}, "defaults": {}}}
        )
        _prepare(session, PkiNodeProjections((projection,)))
        self.assertEqual(session.materialize()["topology"]["nodes"], {})

    def test_rejects_owned_variable_from_defaults_even_when_category_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projection = _projection(Path(directory), kind="fortinet_fortigate")
            session = _session(projection, defaults_env={CRLS: "/manual/crl.pem"})
            with self.assertRaisesRegex(InjectorError, "topology defaults"):
                _prepare(session, PkiNodeProjections((projection,)))

    def test_rejects_missing_authorized_file_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projection = _projection(Path(directory), kind="fortinet_fortigate")
            projection.public_authorities[0].certificate.host_path.unlink()
            session = _session(projection)
            with self.assertRaisesRegex(InjectorError, "unavailable"):
                _prepare(session, PkiNodeProjections((projection,)))
            self.assertNotIn("env", session.materialize()["topology"]["nodes"]["fgt"])

    def test_emits_named_certificate_only_local_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projection = _projection(Path(directory), kind="fortinet_fortigate")
            requested = projection.requested_authorities[0]
            projection = NodePkiProjection(
                node_name=projection.node_name,
                node_kind=projection.node_kind,
                staged_view=projection.staged_view,
                mount_target=projection.mount_target,
                public_authorities=projection.public_authorities,
                trusted_authorities=projection.trusted_authorities,
                requested_authorities=(
                    RequestedAuthorityProjection(
                        requested.scope,
                        requested.name,
                        requested.variant,
                        requested.fingerprint_sha256,
                        requested.certificate,
                        requested.chain,
                        requested.full_chain,
                    ),
                ),
            )
            session = _session(projection)
            _prepare(session, PkiNodeProjections((projection,)))
            self.assertEqual(
                session.materialize()["topology"]["nodes"]["fgt"]["env"][LOCAL_CERTIFICATES],
                "root:/mnt/pki/authorities/global/root/default/certificate.pem",
            )

    def test_rejects_duplicate_local_refname_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projection = _projection(Path(directory), kind="fortinet_fortigate")
            requested = projection.requested_authorities[0]
            duplicate = IssuedIdentityProjection(
                "local/root",
                "c" * 64,
                _projected_file(projection.staged_view, "issued/fgt/root/certificate.pem"),
                _projected_file(projection.staged_view, "issued/fgt/root/private-key.pem"),
                _projected_file(projection.staged_view, "issued/fgt/root/chain.pem"),
                _projected_file(projection.staged_view, "issued/fgt/root/full-chain.pem"),
            )
            projection = NodePkiProjection(
                node_name=projection.node_name,
                node_kind=projection.node_kind,
                staged_view=projection.staged_view,
                mount_target=projection.mount_target,
                public_authorities=projection.public_authorities,
                trusted_authorities=projection.trusted_authorities,
                requested_authorities=(requested,),
                issued_identities=(duplicate,),
            )
            session = _session(projection)
            with self.assertRaisesRegex(InjectorError, "duplicate refname 'root'"):
                _prepare(session, PkiNodeProjections((projection,)))
            self.assertNotIn("env", session.materialize()["topology"]["nodes"]["fgt"])


def _projected_file(view: Path, relative: str) -> ProjectedFile:
    host = view / relative
    host.parent.mkdir(parents=True, exist_ok=True)
    host.write_text("fixture", encoding="utf-8")
    return ProjectedFile(host, PurePosixPath("/mnt/pki") / relative)


def _projection(root: Path, *, kind: str) -> NodePkiProjection:
    view = root / "view"
    public = PublicAuthorityProjection(
        "global",
        "root",
        "default",
        "a" * 64,
        AuthorityClassification.TRUST_ANCHOR,
        _projected_file(view, "authorities/effective/root/default/certificate.pem"),
        _projected_file(view, "authorities/effective/root/default/chain.pem"),
        _projected_file(view, "authorities/effective/root/default/full-chain.pem"),
    )
    issued = IssuedIdentityProjection(
        "local/tls",
        "b" * 64,
        _projected_file(view, "issued/fgt/tls/certificate.pem"),
        _projected_file(view, "issued/fgt/tls/private-key.pem"),
        _projected_file(view, "issued/fgt/tls/chain.pem"),
        _projected_file(view, "issued/fgt/tls/full-chain.pem"),
    )
    requested = RequestedAuthorityProjection(
        "global",
        "root",
        "default",
        "a" * 64,
        _projected_file(view, "authorities/global/root/default/certificate.pem"),
        _projected_file(view, "authorities/global/root/default/chain.pem"),
        _projected_file(view, "authorities/global/root/default/full-chain.pem"),
        _projected_file(view, "private/authorities/global/root/default/private-key.pem"),
    )
    return NodePkiProjection(
        node_name="fgt",
        node_kind=kind,
        staged_view=view,
        mount_target=PurePosixPath("/mnt/pki"),
        public_authorities=(public,),
        trusted_authorities=(public,),
        requested_authorities=(requested,),
        issued_identities=(issued,),
    )


def _session(
    projection: NodePkiProjection, *, defaults_env: dict[str, str] | None = None
) -> TopologySession:
    defaults = {"env": defaults_env} if defaults_env is not None else {}
    document = {
        "topology": {
            "defaults": defaults,
            "nodes": {
                "fgt": {
                    "kind": projection.node_kind,
                    "binds": [f"{projection.staged_view}:{projection.mount_target}:ro"],
                }
            },
        }
    }
    return TopologySession(Path("/tmp/lab.clab.yml"), document)


def _prepare(session: TopologySession, projections: PkiNodeProjections) -> None:
    api = Mock(spec=InvocationAPI)
    api.get_context.return_value = projections
    api.require_context.return_value = session
    event = PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, {})
    FortigatePkiInjector().prepare_call(event, api)
