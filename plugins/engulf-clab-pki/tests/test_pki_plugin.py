from __future__ import annotations

import tempfile
import tomllib
import unittest
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

from engulf_api import InvocationAPI, StateScope
from engulf_clab_lab_parser import TopologySession
from engulf_clab_pki_api import PKI_NODE_PROJECTIONS_CONTEXT, PkiNodeProjections
from engulf_executable_wrapper_api import (
    AfterCallEvent,
    CallMode,
    CallOutcome,
    OutcomeKind,
    PreparationFailedEvent,
    PreparedCallEvent,
)

from engulf_clab_pki.plugin import (
    _INVOCATION_CONTEXT,
    MOUNT_TARGET_ENVIRONMENT,
    PkiPlugin,
    _validate_mount_target,
)


class PkiPluginTest(unittest.TestCase):
    def test_directory_service_uses_available_pinned_image(self) -> None:
        recipe = (
            Path(__file__).parents[1] / "src/engulf_clab_pki/recipes/services.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("image: osixia/openldap:1.5.0", recipe)
        self.assertNotIn("bitnami/openldap", recipe)

    def test_package_declares_parser_writer_freeze_and_schema_ordering(self) -> None:
        package = Path(__file__).parents[1]
        metadata = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = metadata["project"]["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_pki"
        ]
        self.assertEqual(
            dependencies,
            {
                "engulf_clab.freeze": "preprocess=after; postprocess=none",
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.lab_writer": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )

    def _api(self, session: TopologySession, user: Path, workspace: Path) -> Mock:
        api = Mock(spec=InvocationAPI)
        api.require_context.return_value = session
        api.state.side_effect = lambda scope: SimpleNamespace(
            directory=user if scope is StateScope.USER else workspace,
            root=workspace,
        )
        api.leases.return_value = nullcontext()
        return api

    def test_unselected_topology_is_complete_noop(self) -> None:
        session = TopologySession(Path("/tmp/lab.clab.yml"), {"topology": {"nodes": {"r": {}}}})
        api = self._api(session, Path("/tmp/user"), Path("/tmp/work"))
        event = PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, {})
        PkiPlugin().prepare_call(event, api)
        api.state.assert_not_called()
        self.assertEqual(session.materialize(), {"topology": {"nodes": {"r": {}}}})

    def test_opt_in_removes_selector_only_from_derived_topology_and_mounts_every_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            manifest = root / "pki.yaml"
            manifest.write_text(
                "version: 2\n"
                "authorities:\n"
                "  root: {}\n"
                "  issuing: {issuer: root}\n"
                "certificates:\n"
                "  tls: {issuer: issuing}\n",
                encoding="utf-8",
            )
            document = {
                "topology": {
                    "defaults": {"env": {"ECLAB_PKI_MANIFEST": "./pki.yaml"}},
                    "nodes": {
                        "r": {"env": {"ECLAB_PKI_CERTIFICATES": "tls", "ECLAB_PKI_PRIVATE_AUTHORITIES": "root"}},
                        "observer": {},
                    },
                }
            }
            session = TopologySession(topology, document)
            api = self._api(session, root / "user", root / "workspace")
            event = PreparedCallEvent(
                "containerlab", ("deploy", "-t", str(topology)), ("deploy",), CallMode.NORMAL, {}
            )
            PkiPlugin().prepare_call(event, api)
            rendered = session.materialize()
            self.assertNotIn("ECLAB_PKI_MANIFEST", rendered["topology"]["defaults"]["env"])
            for name in ("r", "observer"):
                bind = rendered["topology"]["nodes"][name]["binds"][0]
                self.assertTrue(bind.endswith(":/mnt/eclab/pki:ro"))
            self.assertEqual(
                document["topology"]["defaults"]["env"]["ECLAB_PKI_MANIFEST"], "./pki.yaml"
            )
            published = next(
                call.args[1]
                for call in api.set_context.call_args_list
                if call.args[0] == PKI_NODE_PROJECTIONS_CONTEXT
            )
            self.assertIsInstance(published, PkiNodeProjections)
            self.assertEqual(tuple(node.node_name for node in published.nodes), ("observer", "r"))
            issued = next(node for node in published.nodes if node.node_name == "r")
            self.assertEqual(issued.issued_identities[0].request_name, "local/tls")
            self.assertIsNotNone(issued.requested_authorities[0].private_key)
            self.assertEqual(
                {
                    authority.name: authority.classification.value
                    for authority in issued.public_authorities
                },
                {"issuing": "intermediate", "root": "trust_anchor"},
            )
            observer = next(node for node in published.nodes if node.node_name == "observer")
            self.assertEqual(observer.requested_authorities, ())
            self.assertEqual(observer.issued_identities, ())

    def test_mount_target_node_override_wins_and_controls_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            (root / "pki.yaml").write_text("version: 2\n", encoding="utf-8")
            document = {
                "topology": {
                    "defaults": {
                        "env": {
                            "ECLAB_PKI_MANIFEST": "./pki.yaml",
                            MOUNT_TARGET_ENVIRONMENT: "/default/pki",
                        }
                    },
                    "nodes": {
                        "fgt": {
                            "kind": "fortinet_fortigate",
                            "env": {MOUNT_TARGET_ENVIRONMENT: "/node/pki"},
                        },
                        "observer": {"kind": "linux"},
                    },
                }
            }
            session = TopologySession(topology, document)
            api = self._api(session, root / "user", root / "workspace")
            event = PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, {})
            PkiPlugin().prepare_call(event, api)
            rendered = session.materialize()
            self.assertNotIn(MOUNT_TARGET_ENVIRONMENT, rendered["topology"]["defaults"]["env"])
            self.assertNotIn(MOUNT_TARGET_ENVIRONMENT, rendered["topology"]["nodes"]["fgt"]["env"])
            self.assertTrue(
                rendered["topology"]["nodes"]["fgt"]["binds"][0].endswith(":/node/pki:ro")
            )
            self.assertTrue(
                rendered["topology"]["nodes"]["observer"]["binds"][0].endswith(":/default/pki:ro")
            )
            published = next(
                call.args[1]
                for call in api.set_context.call_args_list
                if call.args[0] == PKI_NODE_PROJECTIONS_CONTEXT
            )
            fgt = next(node for node in published.nodes if node.node_name == "fgt")
            self.assertEqual(fgt.mount_target, PurePosixPath("/node/pki"))

    def test_mount_target_rejects_relative_non_normalized_and_delimited_paths(self) -> None:
        for value in (
            "relative",
            "/",
            "//mnt/pki",
            "/mnt//pki",
            "/mnt/../pki",
            "/mnt/pki;other",
        ):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "normalized absolute POSIX"),
            ):
                _validate_mount_target(value, owner="test")

    def test_later_preparation_failure_removes_attempt_created_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            (root / "pki.yaml").write_text("version: 2\n", encoding="utf-8")
            session = TopologySession(
                topology,
                {
                    "topology": {
                        "defaults": {"env": {"ECLAB_PKI_MANIFEST": "./pki.yaml"}},
                        "nodes": {"fgt": {"kind": "fortinet_fortigate"}},
                    }
                },
            )
            api = self._api(session, root / "user", root / "workspace")
            event = PreparedCallEvent("containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, {})
            plugin = PkiPlugin()
            plugin.prepare_call(event, api)
            prepared = next(
                call.args[1]
                for call in api.set_context.call_args_list
                if call.args[0] == _INVOCATION_CONTEXT
            )
            self.assertTrue(all(path.is_dir() for path in prepared.views))
            api.get_context.return_value = prepared
            plugin.prepare_failed(
                PreparationFailedEvent(
                    "containerlab",
                    ("deploy",),
                    ("deploy",),
                    CallMode.NORMAL,
                    "injector failed",
                ),
                api,
            )
            self.assertTrue(all(not path.exists() for path in prepared.views))

    def test_failed_started_deploy_retains_views_for_partial_containers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "lab.clab.yml"
            (root / "pki.yaml").write_text("version: 2\n", encoding="utf-8")
            session = TopologySession(
                topology,
                {
                    "topology": {
                        "defaults": {"env": {"ECLAB_PKI_MANIFEST": "./pki.yaml"}},
                        "nodes": {"fgt": {"kind": "fortinet_fortigate"}},
                    }
                },
            )
            api = self._api(session, root / "user", root / "workspace")
            plugin = PkiPlugin()
            plugin.prepare_call(
                PreparedCallEvent(
                    "containerlab", ("deploy",), ("deploy",), CallMode.NORMAL, {}
                ),
                api,
            )
            prepared = next(
                call.args[1]
                for call in api.set_context.call_args_list
                if call.args[0] == _INVOCATION_CONTEXT
            )
            api.get_context.return_value = prepared

            plugin.after_call(
                AfterCallEvent(
                    "containerlab",
                    ("deploy",),
                    ("deploy",),
                    CallMode.NORMAL,
                    CallOutcome(OutcomeKind.COMPLETED, 1, True),
                    1.0,
                ),
                api,
            )

            self.assertTrue(all(path.is_dir() for path in prepared.views))
            self.assertTrue((root / "workspace/pki/provisioning.json").is_file())
            api.logger.warning.assert_called_once()
