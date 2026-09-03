from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_clab_pki.catalog import CatalogError, load_catalog, merge_catalogs


class CatalogTest(unittest.TestCase):
    def test_local_replaces_whole_object_and_scoped_global_remains_available(self) -> None:
        catalog = merge_catalogs(
            {
                "version": 1,
                "authorities": {
                    "root": {"subject": {"organization": "global"}, "validity_days": 99}
                },
            },
            {"version": 1, "authorities": {"root": {"subject": {"organization": "local"}}}},
        )
        self.assertNotIn("validity_days", catalog.authorities["root"])
        self.assertEqual(catalog.resolve_authority("root")[0], "local")
        self.assertEqual(catalog.resolve_authority("global/root")[0], "global")
        self.assertEqual(len(catalog.warnings), 1)

    def test_global_definition_cannot_resolve_local_and_cycles_fail(self) -> None:
        with self.assertRaisesRegex(CatalogError, "cannot depend on local"):
            merge_catalogs(
                {"version": 1, "authorities": {"global-ca": {"issuer": "local/local-ca"}}},
                {"version": 1, "authorities": {"local-ca": {}}},
            )
        with self.assertRaisesRegex(CatalogError, "cycle"):
            merge_catalogs(
                {"version": 1},
                {"version": 1, "authorities": {"a": {"issuer": "b"}, "b": {"issuer": "a"}}},
            )

    def test_direct_invalid_edit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pki.yaml"
            path.write_text("authorities: [broken]\n", encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "must be a mapping"):
                load_catalog(path, required=True)
