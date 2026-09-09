from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, ObjectIdentifier

from engulf_clab_pki.catalog import bind_topology_requests, merge_catalogs
from engulf_clab_pki.material import generate_catalog
from engulf_clab_pki.projections import build_node_projections
from engulf_clab_pki.views import build_views


class MaterialTest(unittest.TestCase):
    def test_default_certificate_start_is_two_days_in_the_past(self) -> None:
        catalog = merge_catalogs(
            {"version": 2}, {"version": 2, "authorities": {"root": {}}}
        )
        before = datetime.now(UTC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            material = generate_catalog(
                catalog, user_root=root / "user", workspace_root=root / "work"
            )
        after = datetime.now(UTC)
        not_before = material.authorities[("local", "root", "default")].certificate.not_valid_before_utc
        self.assertGreaterEqual(not_before, before - timedelta(days=2, seconds=2))
        self.assertLessEqual(not_before, after - timedelta(days=2) + timedelta(seconds=2))

    def test_deep_cross_signed_generation_and_private_view_isolation(self) -> None:
        catalog = merge_catalogs(
            {"version": 2},
            {
                "version": 2,
                "authorities": {
                    "root-a": {},
                    "root-b": {},
                    "issuing": {"issuer": "root-a", "variants": {"via-b": {"issuer": "root-b"}}},
                },
                "certificates": {"tls": {"issuer": "issuing/via-b"}},
            },
        )
        bind_topology_requests(catalog, {"topology": {"nodes": {
            "router": {"env": {"ECLAB_PKI_CERTIFICATES": "tls", "ECLAB_PKI_PRIVATE_AUTHORITIES": "root-a"}},
            "observer": {},
        }}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            material = generate_catalog(
                catalog, user_root=root / "user", workspace_root=root / "work"
            )
            self.assertEqual(len(material.authorities), 4)
            issuing = material.authorities[("local", "issuing", "via-b")]
            self.assertEqual(
                issuing.certificate.issuer,
                material.authorities[("local", "root-b", "default")].certificate.subject,
            )
            self.assertEqual(
                issuing.private_key.public_key().public_numbers(),
                material.authorities[("local", "issuing", "default")]
                .private_key.public_key()
                .public_numbers(),
            )
            catalog.local_catalog["_topology_nodes"] = ["router", "observer"]
            views, _ = build_views(catalog, material, root / "work")
            self.assertTrue((views["router"] / "issued/router/local/tls/private-key.pem").is_file())
            self.assertTrue(
                (
                    views["router"] / "private/authorities/local/root-a/default/private-key.pem"
                ).is_file()
            )
            self.assertFalse((views["observer"] / "private").exists())
            self.assertFalse((views["observer"] / "issued").exists())
            topology = {
                "topology": {
                    "nodes": {
                        "observer": {"kind": "linux"},
                        "router": {"kind": "fortinet_fortigate"},
                    }
                }
            }
            projections = build_node_projections(
                catalog,
                material,
                topology,
                views,
                {
                    "observer": PurePosixPath("/mnt/pki"),
                    "router": PurePosixPath("/mnt/pki"),
                },
            )
            router = next(item for item in projections.nodes if item.node_name == "router")
            classifications = {
                (item.name, item.variant): item.classification.value
                for item in router.public_authorities
            }
            self.assertEqual(classifications[("root-a", "default")], "trust_anchor")
            self.assertEqual(classifications[("issuing", "default")], "intermediate")
            self.assertEqual(classifications[("issuing", "via-b")], "intermediate")
            self.assertIsNotNone(router.requested_authorities[0].private_key)

    def test_definition_change_rotates_instead_of_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = merge_catalogs({"version": 2}, {"version": 2, "authorities": {"root": {}}})
            one = generate_catalog(first, user_root=root / "u", workspace_root=root / "w")
            second = merge_catalogs(
                {"version": 2}, {"version": 2, "authorities": {"root": {"validity_days": 1000}}}
            )
            two = generate_catalog(second, user_root=root / "u", workspace_root=root / "w")
            self.assertNotEqual(
                one.authorities[("local", "root", "default")].generation,
                two.authorities[("local", "root", "default")].generation,
            )
            generations = root / "w/pki/authorities/root/generations/default"
            self.assertEqual(len(list(generations.iterdir())), 2)

    def test_rich_extensions_and_optional_formats(self) -> None:
        catalog = merge_catalogs(
            {"version": 2},
            {
                "version": 2,
                "authorities": {"root": {"algorithm": "ed25519"}},
                "certificates": {
                    "tls": {
                                "issuer": "root",
                                "profile": "tls-peer",
                                "algorithm": {"name": "ecdsa", "curve": "secp384r1"},
                                "subject": {
                                    "organization": "Example",
                                    "common_name": "router.example",
                                },
                                "sans": {"dns": ["router.example"], "ip": ["192.0.2.1"]},
                                "policies": ["1.2.3.4"],
                                "extensions": [{"oid": "1.2.3.5", "value": "test"}],
                                "formats": ["pem", "der", "pkcs12"],
                    }
                },
            },
        )
        bind_topology_requests(catalog, {"topology": {"nodes": {"router": {"env": {"ECLAB_PKI_CERTIFICATES": "tls"}}}}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            material = generate_catalog(catalog, user_root=root / "u", workspace_root=root / "w")
            leaf = material.leaves[("router", "local/tls")]
            self.assertTrue((leaf.directory / "certificate.der").is_file())
            self.assertTrue((leaf.directory / "identity.p12").is_file())
            self.assertEqual(
                leaf.certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value,
                x509.ExtendedKeyUsage(
                    [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
                ),
            )
            self.assertEqual(
                leaf.certificate.extensions.get_extension_for_oid(
                    ObjectIdentifier("1.2.3.5")
                ).value.value,
                b"test",
            )
            catalog.local_catalog["_topology_nodes"] = ["router"]
            views, _ = build_views(catalog, material, root / "w")
            inventory = json.loads((views["router"] / "inventory.json").read_text())
            self.assertEqual(inventory["issued_identities"][0]["formats"], ["pem", "der", "pkcs12"])

    def test_offline_ml_dsa_generation_when_provider_supports_it(self) -> None:
        catalog = merge_catalogs(
            {"version": 2},
            {
                "version": 2,
                "authorities": {"root": {"algorithm": {"name": "ml-dsa", "parameter_set": "44"}}},
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            material = generate_catalog(catalog, user_root=root / "u", workspace_root=root / "w")
            self.assertEqual(
                material.authorities[
                    ("local", "root", "default")
                ].certificate.signature_algorithm_oid.dotted_string,
                "2.16.840.1.101.3.4.3.17",
            )

    def test_omitted_subject_cn_uses_node_without_adding_node_san(self) -> None:
        catalog = merge_catalogs(
            {"version": 2},
            {
                "version": 2,
                "authorities": {"root": {"algorithm": {"name": "ecdsa"}}},
                "certificates": {
                    "peer": {"issuer": "root", "algorithm": {"name": "ecdsa"}}
                },
            },
        )
        bind_topology_requests(
            catalog,
            {
                "topology": {
                    "nodes": {
                        "one": {"env": {"ECLAB_PKI_CERTIFICATES": "peer"}},
                        "two": {"env": {"ECLAB_PKI_CERTIFICATES": "peer"}},
                    }
                }
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            material = generate_catalog(catalog, user_root=root / "u", workspace_root=root / "w")
            for node in ("one", "two"):
                certificate = material.leaves[(node, "local/peer")].certificate
                self.assertEqual(
                    certificate.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value,
                    node,
                )
                with self.assertRaises(x509.ExtensionNotFound):
                    certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
