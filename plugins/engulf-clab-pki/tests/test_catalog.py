from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_clab_pki.catalog import (
    CatalogError,
    bind_topology_requests,
    load_catalog,
    merge_catalogs,
)


class CatalogTest(unittest.TestCase):
    def test_requests_inherit_from_kinds_and_groups_with_empty_node_override(self) -> None:
        catalog = merge_catalogs({"version": 2}, {"version": 2, "authorities": {"root": {}}, "certificates": {
            "kind-cert": {"issuer": "root"}, "group-cert": {"issuer": "root"},
        }})
        bind_topology_requests(catalog, {"topology": {
            "defaults": {"kind": "linux"},
            "kinds": {"linux": {"env": {"ECLAB_PKI_CERTIFICATES": "kind-cert", "ECLAB_PKI_TRUST_MODE": "none"}}},
            "groups": {"clients": {"env": {"ECLAB_PKI_CERTIFICATES": "group-cert", "ECLAB_PKI_PRIVATE_AUTHORITIES": "root"}}},
            "nodes": {"kind": {}, "group": {"group": "clients"}, "empty": {"group": "clients", "env": {"ECLAB_PKI_CERTIFICATES": ""}}},
        }})
        self.assertEqual(catalog.nodes["kind"]["certificates"][0]["name"], "local/kind-cert")
        self.assertEqual(catalog.nodes["group"]["certificates"][0]["name"], "local/group-cert")
        self.assertEqual(catalog.nodes["empty"]["certificates"], [])
        self.assertEqual(catalog.nodes["group"]["authorities"][0]["name"], "local/root")
        self.assertEqual(catalog.nodes["group"]["trusted_authorities"], [])

    def test_local_replaces_whole_object_and_scoped_global_remains_available(self) -> None:
        catalog = merge_catalogs(
            {
                "version": 2,
                "authorities": {
                    "root": {"subject": {"organization": "global"}, "validity_days": 99}
                },
            },
            {"version": 2, "authorities": {"root": {"subject": {"organization": "local"}}}},
        )
        self.assertNotIn("validity_days", catalog.authorities["root"])
        self.assertEqual(catalog.resolve_authority("root")[0], "local")
        self.assertEqual(catalog.resolve_authority("global/root")[0], "global")
        self.assertEqual(len(catalog.warnings), 1)

    def test_global_definition_cannot_resolve_local_and_cycles_fail(self) -> None:
        with self.assertRaisesRegex(CatalogError, "cannot depend on local"):
            merge_catalogs(
                {"version": 2, "authorities": {"global-ca": {"issuer": "local/local-ca"}}},
                {"version": 2, "authorities": {"local-ca": {}}},
            )
        with self.assertRaisesRegex(CatalogError, "cycle"):
            merge_catalogs(
                {"version": 2},
                {"version": 2, "authorities": {"a": {"issuer": "b"}, "b": {"issuer": "a"}}},
            )

    def test_direct_invalid_edit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pki.yaml"
            path.write_text("version: 2\nauthorities: [broken]\n", encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "must be a mapping"):
                load_catalog(path, required=True)

    def test_version_one_is_rejected_with_migration_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pki.yaml"
            path.write_text("version: 1\n", encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "ECLAB_PKI_CERTIFICATES"):
                load_catalog(path, required=True)

    def test_named_certificate_requests_are_canonical_and_node_lists_replace_defaults(self) -> None:
        catalog = merge_catalogs(
            {
                "version": 2,
                "authorities": {"root": {}},
                "certificates": {"user": {"issuer": "root"}},
            },
            {
                "version": 2,
                "authorities": {"local-root": {}},
                "certificates": {"user": {"issuer": "local-root"}},
            },
        )
        bind_topology_requests(
            catalog,
            {
                "topology": {
                    "defaults": {"env": {"ECLAB_PKI_CERTIFICATES": "global/user"}},
                    "nodes": {
                        "defaulted": {},
                        "overridden": {"env": {"ECLAB_PKI_CERTIFICATES": "user"}},
                    },
                }
            },
        )
        self.assertEqual(catalog.nodes["defaulted"]["certificates"][0]["name"], "global/user")
        self.assertEqual(catalog.nodes["overridden"]["certificates"][0]["name"], "local/user")
