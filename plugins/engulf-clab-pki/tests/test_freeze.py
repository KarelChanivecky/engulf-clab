from __future__ import annotations

import argparse
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from engulf_clab_freeze.command import freeze as freeze_archive
from engulf_clab_freeze.defrost import defrost
from engulf_clab_freeze_api import DefrostContext, FreezeContext, FreezeError

from engulf_clab_pki.catalog import bind_topology_requests, load_catalog, merge_catalogs
from engulf_clab_pki.freeze import (
    PkiFreezeContributor,
    _decrypt,
    _encrypt,
    _external_bindings,
    _passphrase,
    _portable_external_stores,
    _rewrite_authority_references,
    _rewrite_topology_authority_references,
    _topology_certificate_requests,
)
from engulf_clab_pki.material import generate_catalog


class FreezeTest(unittest.TestCase):
    def test_topology_pki_requests_use_the_effective_node_at_every_level(self) -> None:
        for level in ("defaults", "kinds", "groups", "nodes"):
            with self.subTest(level=level):
                node = {"kind": "linux", "group": "clients"}
                topology: dict[str, object] = {"nodes": {"router": node}}
                definition = {"env": {"ECLAB_PKI_CERTIFICATES": "global/site-tls"}}
                if level == "defaults":
                    topology[level] = definition
                elif level == "nodes":
                    node.update(definition)
                else:
                    topology[level] = {
                        "linux" if level == "kinds" else "clients": definition
                    }
                self.assertEqual(
                    _topology_certificate_requests({"topology": topology}),
                    (("router", "global/site-tls"),),
                )

    def test_inherited_authority_references_are_rewritten_at_their_origin(self) -> None:
        document = {
            "topology": {
                "defaults": {"kind": "linux"},
                "kinds": {"linux": {"group": "clients"}},
                "groups": {
                    "clients": {
                        "env": {"ECLAB_PKI_PRIVATE_AUTHORITIES": "site-root"}
                    }
                },
                "nodes": {"router": {}},
            }
        }

        _rewrite_topology_authority_references(
            document, "site-root", "global/recipient-root"
        )

        self.assertEqual(
            document["topology"]["groups"]["clients"]["env"][
                "ECLAB_PKI_PRIVATE_AUTHORITIES"
            ],
            "global/recipient-root",
        )

    def test_external_manifest_is_vendored_and_rebased_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            staging = root / "staging"
            source.mkdir()
            staging.mkdir()
            imported = source / ".eclab-pki-import" / "authorities" / "root"
            imported.mkdir(parents=True)
            (imported / "private-key.pem").write_text("private", encoding="utf-8")
            staged_imported = staging / ".eclab-pki-import" / "authorities" / "root"
            staged_imported.mkdir(parents=True)
            (staged_imported / "private-key.pem").write_text("private", encoding="utf-8")
            (root / "outside.yaml").write_text(
                "version: 2\nauthorities: {root: {}}\n", encoding="utf-8"
            )
            topology = {
                "topology": {
                    "defaults": {"env": {"ECLAB_PKI_MANIFEST": "../outside.yaml"}},
                    "nodes": {},
                }
            }
            source_topology = source / "lab.clab.yml"
            staged_topology = staging / "lab.clab.yml"
            source_topology.write_text(yaml.safe_dump(topology), encoding="utf-8")
            staged_topology.write_text(yaml.safe_dump(topology), encoding="utf-8")
            metadata = PkiFreezeContributor().freeze(
                FreezeContext(
                    source_topology,
                    staged_topology,
                    source,
                    staging,
                    None,
                    None,
                    argparse.Namespace(include_pki_secrets=False, pki_passphrase_file=None),
                    {},
                )
            )
            self.assertEqual(metadata["manifest"], "pki.yaml")
            copied = yaml.safe_load(staged_topology.read_text(encoding="utf-8"))
            self.assertEqual(
                copied["topology"]["defaults"]["env"]["ECLAB_PKI_MANIFEST"], "./pki.yaml"
            )
            self.assertNotIn("private-key", (staging / "pki.yaml").read_text(encoding="utf-8"))
            self.assertFalse((staging / ".eclab-pki-import").exists())

    def test_encrypted_bundle_authenticates(self) -> None:
        payload = _encrypt(b"private", b"correct horse")
        self.assertEqual(_decrypt(payload, b"correct horse"), b"private")
        with self.assertRaisesRegex(Exception, "authentication failed"):
            _decrypt(payload, b"wrong")

    def test_passphrase_file_must_be_owner_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "passphrase"
            path.write_text("correct horse\n", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaisesRegex(FreezeError, "group or others"):
                _passphrase(str(path), "unused")
            path.chmod(0o600)
            self.assertEqual(_passphrase(str(path), "unused"), b"correct horse")

    def test_string_authority_request_is_rewritten(self) -> None:
        document = {
            "nodes": {
                "router": {
                    "authorities": ["global/site-root/default"],
                    "certificates": [{"name": "tls", "issuer": "site-root"}],
                }
            }
        }
        _rewrite_authority_references(document, "site-root", "global/recipient-root")
        self.assertEqual(
            document["nodes"]["router"]["authorities"],
            ["global/recipient-root/default"],
        )
        self.assertEqual(
            document["nodes"]["router"]["certificates"][0]["issuer"],
            "global/recipient-root",
        )

    def test_materialized_explicit_store_becomes_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            catalog = {
                "version": 2,
                "stores": {"offbox": {"type": "directory", "path": str(external)}},
                "authorities": {"root": {"store": "offbox"}},
            }
            generate_catalog(
                merge_catalogs({"version": 2}, catalog),
                user_root=root / "user",
                workspace_root=root / "workspace",
            )
            portable = yaml.safe_load(yaml.safe_dump(catalog))
            bindings = {}
            _portable_external_stores(catalog, portable, bindings)
            self.assertNotIn("root", portable["authorities"])
            self.assertEqual(len(bindings["root"]["fingerprint_sha256"]), 64)
            self.assertIn("BEGIN CERTIFICATE", bindings["root"]["public_chain_pem"])

    def test_encrypted_authority_round_trip_preserves_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            frozen = root / "frozen"
            workspace = root / "workspace-state"
            source.mkdir()
            frozen.mkdir()
            manifest_document = {
                "version": 2,
                "authorities": {"root": {"freeze": {"exportable": True}}},
                "certificates": {
                    "tls": {"issuer": "root", "freeze": {"exportable": True}}
                },
            }
            (source / "pki.yaml").write_text(yaml.safe_dump(manifest_document), encoding="utf-8")
            topology_document = {
                "topology": {
                    "defaults": {"env": {"ECLAB_PKI_MANIFEST": "./pki.yaml"}},
                    "nodes": {
                        "router": {"env": {"ECLAB_PKI_CERTIFICATES": "tls"}}
                    },
                }
            }
            source_topology = source / "lab.clab.yml"
            staged_topology = frozen / "lab.clab.yml"
            source_topology.write_text(yaml.safe_dump(topology_document), encoding="utf-8")
            staged_topology.write_text(yaml.safe_dump(topology_document), encoding="utf-8")
            effective = merge_catalogs({"version": 2}, manifest_document)
            bind_topology_requests(effective, topology_document)
            generated = generate_catalog(
                effective,
                user_root=root / "user-state",
                workspace_root=workspace,
            )
            fingerprint = generated.authorities[("local", "root", "default")].fingerprint
            leaf_fingerprint = generated.leaves[("router", "local/tls")].fingerprint
            passphrase = root / "passphrase"
            passphrase.write_text("portable secret\n", encoding="utf-8")
            passphrase.chmod(0o600)
            contributor = PkiFreezeContributor()
            metadata = contributor.freeze(
                FreezeContext(
                    source_topology,
                    staged_topology,
                    source,
                    frozen,
                    workspace,
                    root / "user-state",
                    argparse.Namespace(
                        include_pki_secrets=True, pki_passphrase_file=str(passphrase)
                    ),
                    {},
                )
            )
            self.assertIsNotNone(metadata)
            contributor.defrost(
                DefrostContext(
                    staged_topology,
                    frozen,
                    frozen,
                    metadata,
                    argparse.Namespace(
                        pki_authority=None,
                        no_pki_prompt=True,
                        pki_passphrase_file=str(passphrase),
                    ),
                    {},
                    root / "recipient-user",
                )
            )
            restored_catalog = merge_catalogs(
                {"version": 2}, load_catalog(frozen / "pki.yaml", required=True)
            )
            bind_topology_requests(
                restored_catalog,
                yaml.safe_load(staged_topology.read_text(encoding="utf-8")),
            )
            restored = generate_catalog(
                restored_catalog,
                user_root=root / "recipient-user",
                workspace_root=root / "recipient-workspace",
            )
            self.assertEqual(
                restored.authorities[("local", "root", "default")].fingerprint,
                fingerprint,
            )
            self.assertEqual(
                restored.leaves[("router", "local/tls")].fingerprint,
                leaf_fingerprint,
            )

    def test_encrypted_global_binding_restores_into_local_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            frozen = root / "frozen"
            workspace = root / "workspace-state"
            user = root / "user-state"
            source.mkdir()
            frozen.mkdir()
            user.mkdir()
            global_document = {
                "version": 2,
                "authorities": {"site-root": {"freeze": {"exportable": True}}},
            }
            local_document = {
                "version": 2,
                "authorities": {
                    "issuing": {
                        "issuer": "global/site-root",
                        "freeze": {"exportable": True},
                    }
                },
            }
            (user / "global.yaml").write_text(yaml.safe_dump(global_document), encoding="utf-8")
            (source / "pki.yaml").write_text(yaml.safe_dump(local_document), encoding="utf-8")
            topology_document = {
                "topology": {
                    "defaults": {"env": {"ECLAB_PKI_MANIFEST": "./pki.yaml"}},
                    "nodes": {},
                }
            }
            source_topology = source / "lab.clab.yml"
            staged_topology = frozen / "lab.clab.yml"
            source_topology.write_text(yaml.safe_dump(topology_document), encoding="utf-8")
            staged_topology.write_text(yaml.safe_dump(topology_document), encoding="utf-8")
            generated = generate_catalog(
                merge_catalogs(global_document, local_document),
                user_root=user,
                workspace_root=workspace,
            )
            expected = {
                name: generated.authorities[(scope, name, "default")].fingerprint
                for scope, name in (("global", "site-root"), ("local", "issuing"))
            }
            passphrase = root / "passphrase"
            passphrase.write_text("portable secret\n", encoding="utf-8")
            passphrase.chmod(0o600)
            contributor = PkiFreezeContributor()
            metadata = contributor.freeze(
                FreezeContext(
                    source_topology,
                    staged_topology,
                    source,
                    frozen,
                    workspace,
                    user,
                    argparse.Namespace(
                        include_pki_secrets=True, pki_passphrase_file=str(passphrase)
                    ),
                    {},
                )
            )
            contributor.defrost(
                DefrostContext(
                    staged_topology,
                    frozen,
                    frozen,
                    metadata,
                    argparse.Namespace(
                        pki_authority=None,
                        no_pki_prompt=True,
                        pki_passphrase_file=str(passphrase),
                    ),
                    {},
                    root / "recipient-user",
                )
            )
            restored_catalog = merge_catalogs(
                {"version": 2}, load_catalog(frozen / "pki.yaml", required=True)
            )
            restored = generate_catalog(
                restored_catalog,
                user_root=root / "recipient-user",
                workspace_root=root / "recipient-workspace",
            )
            self.assertEqual(
                restored.authorities[("local", "site-root", "default")].fingerprint,
                expected["site-root"],
            )
            self.assertEqual(
                restored.authorities[("local", "issuing", "default")].fingerprint,
                expected["issuing"],
            )

    def test_unqualified_global_reference_becomes_fingerprinted_public_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            global_catalog = {"version": 2, "authorities": {"site-root": {}}}
            (state / "global.yaml").write_text(yaml.safe_dump(global_catalog), encoding="utf-8")
            generate_catalog(
                merge_catalogs(global_catalog, {"version": 2}),
                user_root=state,
                workspace_root=state / "workspace",
            )
            bindings = _external_bindings(
                {
                    "version": 2,
                    "authorities": {},
                    "nodes": {"router": {"certificates": [{"name": "tls", "issuer": "site-root"}]}},
                },
                state,
            )
            binding = bindings["site-root"]
            self.assertEqual(len(binding["fingerprint_sha256"]), 64)
            self.assertIn("BEGIN CERTIFICATE", binding["public_chain_pem"])

    def test_format_two_archive_round_trip_vendors_external_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "lab"
            source.mkdir()
            outside = root / "outside.yaml"
            outside.write_text("version: 2\nauthorities: {root: {}}\n", encoding="utf-8")
            topology = source / "lab.clab.yml"
            topology.write_text(
                yaml.safe_dump(
                    {
                        "topology": {
                            "defaults": {"env": {"ECLAB_PKI_MANIFEST": "../outside.yaml"}},
                            "nodes": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
            archive = root / "share.tar.gz"
            contributor = PkiFreezeContributor()
            freeze_args = argparse.Namespace(include_pki_secrets=False, pki_passphrase_file=None)
            with patch("engulf_clab_freeze.command._download_wheels"):
                freeze_archive(
                    topology,
                    archive,
                    workspace=None,
                    user_state=SimpleNamespace(directory=root / "user"),
                    contributors=(contributor,),
                    contributor_arguments=freeze_args,
                )
            with tarfile.open(archive, "r:gz") as handle:
                frozen = yaml.safe_load(handle.extractfile("share/lab.clab.yml").read())
                self.assertIn("share/pki.yaml", handle.getnames())
            self.assertEqual(frozen["x-engulf-clab-freeze"]["format"], 2)
            self.assertIn("engulf_clab.pki", frozen["x-engulf-clab-freeze"]["contributors"])
            destination = root / "restored"
            defrost_args = argparse.Namespace(
                pki_authority=None, no_pki_prompt=True, pki_passphrase_file=None
            )
            defrost(
                archive,
                destination,
                prepare_runtime=False,
                contributors=(contributor,),
                contributor_arguments=defrost_args,
                user_state=root / "recipient-user",
            )
            restored = yaml.safe_load((destination / "lab.clab.yml").read_text(encoding="utf-8"))
            self.assertEqual(
                restored["topology"]["defaults"]["env"]["ECLAB_PKI_MANIFEST"],
                "./pki.yaml",
            )
