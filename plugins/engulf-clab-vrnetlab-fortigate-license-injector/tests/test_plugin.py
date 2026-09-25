from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import Mock

from engulf_api import InvocationAPI
from engulf_clab_lab_parser import TopologySession
from engulf_clab_license_pool import LicenseSelection
from engulf_executable_wrapper_api import CallMode, PreparedCallEvent

from engulf_clab_vrnetlab_fortigate_license_injector.plugin import (
    LICENSE_TARGET,
    FortigateLicenseInjector,
    InjectorError,
)


class FortigateLicenseInjectorTest(unittest.TestCase):
    def test_package_declares_parser_license_pool_pki_writer_and_schema_ordering(self) -> None:
        package = Path(__file__).parents[1]
        metadata = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = metadata["project"]["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_vrnetlab_fortigate_license_injector"
        ]
        self.assertEqual(
            dependencies,
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.license_pool": "preprocess=before; postprocess=none",
                "engulf_clab.pki": "preprocess=before; postprocess=none",
                "engulf_clab.lab_writer": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )

    def test_injects_read_only_bind_and_preserves_existing_binds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _license(root)
            session = _session(source, binds=["/host/pki:/mnt/pki:ro"])
            _prepare(session, _selection(source))
            binds = session.materialize()["topology"]["nodes"]["fgt"]["binds"]
            self.assertEqual(
                binds,
                [
                    "/host/pki:/mnt/pki:ro",
                    f"{source}:{LICENSE_TARGET}:ro",
                ],
            )

    def test_composes_with_an_earlier_whole_list_bind_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _license(root)
            session = _session(source)
            session.editor("engulf_clab.pki").modify(
                ("topology", "nodes", "fgt", "binds"),
                ["/workspace/pki:/mnt/pki:ro"],
            )
            _prepare(session, _selection(source))
            self.assertEqual(
                session.materialize()["topology"]["nodes"]["fgt"]["binds"],
                ["/workspace/pki:/mnt/pki:ro", f"{source}:{LICENSE_TARGET}:ro"],
            )

    def test_existing_matching_inherited_mount_is_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _license(root)
            session = TopologySession(
                Path("/tmp/lab.clab.yml"),
                {
                    "topology": {
                        "kinds": {
                            "fortinet_fortigate": {"binds": [f"{source}:{LICENSE_TARGET}:ro"]}
                        },
                        "nodes": {"fgt": {"kind": "fortinet_fortigate", "license": str(source)}},
                    }
                },
            )
            _prepare(session, _selection(source))
            self.assertNotIn("binds", session.materialize()["topology"]["nodes"]["fgt"])

    def test_conflicting_target_fails_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _license(root)
            session = _session(source, binds=["/different/license:/tftpboot/appliance.lic:ro"])
            with self.assertRaisesRegex(InjectorError, "conflicting bind"):
                _prepare(session, _selection(source))
            self.assertEqual(
                session.materialize()["topology"]["nodes"]["fgt"]["binds"],
                ["/different/license:/tftpboot/appliance.lic:ro"],
            )

    def test_rejects_missing_or_symlinked_selected_copy_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.lic"
            session = _session(missing)
            with self.assertRaisesRegex(InjectorError, "unavailable"):
                _prepare(session, _selection(missing))
            self.assertNotIn("binds", session.materialize()["topology"]["nodes"]["fgt"])

            source = _license(root, "actual.lic")
            link = root / "selected.lic"
            link.symlink_to(source)
            linked_session = _session(link)
            with self.assertRaisesRegex(InjectorError, "unavailable"):
                _prepare(linked_session, _selection(link))
            self.assertNotIn("binds", linked_session.materialize()["topology"]["nodes"]["fgt"])

    def test_missing_context_and_non_mutating_command_are_noops(self) -> None:
        api = Mock(spec=InvocationAPI)
        api.get_context.return_value = None
        event = _event(("deploy",))
        FortigateLicenseInjector().prepare_call(event, api)
        api.require_context.assert_not_called()

        api.get_context.reset_mock()
        api.get_context.return_value = {"fgt": object()}
        FortigateLicenseInjector().prepare_call(_event(("inspect",)), api)
        api.get_context.assert_not_called()

    def test_skips_removed_build_node_and_non_fortigate_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _license(root)
            session = TopologySession(
                Path("/tmp/lab.clab.yml"),
                {
                    "topology": {
                        "nodes": {
                            "linux": {
                                "kind": "linux",
                                "image": "alpine:latest",
                                "license": str(source),
                            }
                        }
                    }
                },
            )
            _prepare(session, _selection(source, node="linux"))
            _prepare(session, _selection(source, node="removed"))
            nodes = session.materialize()["topology"]["nodes"]
            self.assertNotIn("binds", nodes["linux"])
            self.assertNotIn("removed", nodes)

    def test_rejects_invalid_selection_context(self) -> None:
        api = Mock(spec=InvocationAPI)
        api.get_context.return_value = {"fgt": object()}
        api.require_context.return_value = TopologySession(
            Path("/tmp/lab.clab.yml"), {"topology": {"nodes": {}}}
        )
        with self.assertRaisesRegex(InjectorError, "invalid selected license entry"):
            FortigateLicenseInjector().prepare_call(_event(("deploy",)), api)


def _license(root: Path, name: str = "registered.lic") -> Path:
    path = root / name
    path.write_bytes(b"private license fixture")
    return path


def _selection(path: Path, *, node: str = "fgt") -> LicenseSelection:
    return LicenseSelection(
        node=node,
        source_name=path.name,
        source_path="/private/pool/never-used-by-injector.lic",
        pool="/private/pool",
    )


def _session(
    path: Path, *, binds: list[str] | None = None, kind: str = "fortinet_fortigate"
) -> TopologySession:
    node = {"kind": kind, "image": "vrnetlab/fortinet_fortigateb:8.0.0", "license": str(path)}
    if binds is not None:
        node["binds"] = binds
    return TopologySession(Path("/tmp/lab.clab.yml"), {"topology": {"nodes": {"fgt": node}}})


def _prepare(session: TopologySession, selection: object) -> None:
    api = Mock(spec=InvocationAPI)
    if isinstance(selection, LicenseSelection):
        selection = {selection.node: selection}
    api.get_context.return_value = selection
    api.require_context.return_value = session
    FortigateLicenseInjector().prepare_call(_event(("deploy",)), api)


def _event(arguments: tuple[str, ...]) -> PreparedCallEvent:
    return PreparedCallEvent("containerlab", arguments, arguments, CallMode.NORMAL, {})
