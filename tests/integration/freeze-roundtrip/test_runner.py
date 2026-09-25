"""Host-free tests: pytest THIS_FILE. Importing the suite never deploys a lab."""

import copy
import hashlib
import io
import json
import runpy
import sys
import tarfile
import uuid
from itertools import combinations, product
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from lab import (
    WAN_IMAGE,
    make_source,
)
from matrix import DIMENSIONS, IMAGES, Case, cases, coverage, matrix
from probes import fortigate_default_route_uses
from runner import rewrite_archive
from support import (
    CheckFailed,
    Report,
    expected_failure,
    merge_catalog,
    normalize,
    owned_container,
)


@pytest.mark.parametrize("mode", IMAGES)
def test_matrix_covers_every_feasible_pair_independently(mode):
    selected = matrix(mode)
    dimensions = dict(DIMENSIONS, image=IMAGES[mode])
    for first, second in combinations(dimensions, 2):
        actual = {(getattr(case, first), getattr(case, second)) for case in selected}
        assert actual == set(product(dimensions[first], dimensions[second]))
    assert len(selected) < 50
    assert selected == matrix(mode)
    assert len({case.id for case in cases(mode)}) == len(cases(mode))
    assert coverage(mode, selected)["missing"] == []
    assert coverage(mode, selected[:1])["missing"]


def test_archive_cache_key_does_not_merge_different_archive_content():
    base = Case("test", "lean")
    assert base.archive_key != Case("test", "lean", image="external").archive_key
    assert base.archive_key != Case("test", "lean", pki="workspace-export").archive_key
    assert (
        Case("a", "lean", pki="user-auto").archive_key
        == Case("b", "lean", pki="user-explicit").archive_key
    )
    assert (
        Case("a", "offline", image="bundle-load").archive_key
        == Case("b", "offline", image="bundle-explicit").archive_key
    )


def test_recipient_answers_create_private_saved_image_for_archive_variable(tmp_path):
    import json
    import tarfile
    from unittest.mock import Mock

    import yaml
    from runner import Suite

    image = "eclab.containers.pki/debian:latest"
    variable = "ECLAB_FREEZE_BASE_ARCHIVE_12345678"
    archive = tmp_path / "source.tar.gz"
    topology = {
        "topology": {
            "nodes": {
                "fortigate": {
                    "image": "${ECLAB_FREEZE_FORTIGATE_IMAGE_12345678}",
                    "env": {"BUILD_ARCHIVE": "${ECLAB_FREEZE_BASE_ARCHIVE_12345678}"},
                }
            }
        }
    }
    with tarfile.open(archive, "w:gz") as saved:
        for name, payload in (
            ("source/lab.clab.yml", yaml.safe_dump(topology).encode()),
            (
                "source/images.freeze.json",
                json.dumps(
                    {
                        "images": [
                            {
                                "image": image,
                                "action": "archive",
                                "archive_variable": variable,
                                "reason": "recipient supplies a build dependency archive",
                            }
                        ]
                    }
                ).encode(),
            ),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            saved.addfile(member, io.BytesIO(payload))

    suite = object.__new__(Suite)
    suite.root = tmp_path
    suite.image = "freeze-roundtrip/fortigate:test"
    suite.image_source = tmp_path / "fortigate.zip"
    suite.commands = Mock()

    def save_image(arguments, **_kwargs):
        Path(arguments[4]).write_bytes(b"docker save fixture")

    suite.commands.run.side_effect = save_image
    answers = suite.answers(archive)
    result = Path(answers[variable])
    assert result.is_relative_to(tmp_path / "external-image-inputs")
    assert result.read_bytes() == b"docker save fixture"
    assert result.stat().st_mode & 0o777 == 0o600
    suite.commands.run.assert_called_once_with(
        ["docker", "image", "save", "--output", result, image],
        timeout=900,
        private=True,
    )
    assert answers["ECLAB_FREEZE_FORTIGATE_IMAGE_12345678"] == suite.image
    assert answers[variable] == str(result)
    assert hashlib.sha256(image.encode()).hexdigest() in result.name


def test_failed_source_baseline_does_not_mark_source_ready(tmp_path, monkeypatch):
    import runner
    from runner import Suite

    source = tmp_path / "source"
    suite = object.__new__(Suite)
    suite.root = tmp_path
    suite.run_id = "test123"
    suite.password = "test-only"
    suite.image = "fortigate:test"
    suite.sources = {}
    suite.baselines = {}
    suite.schema = object()
    suite.eclab = tmp_path / "eclab"
    suite.commands = __import__("unittest.mock", fromlist=["Mock"]).Mock()
    suite.deploy = __import__("unittest.mock", fromlist=["Mock"]).Mock(
        side_effect=CheckFailed("baseline failed")
    )
    monkeypatch.setattr(runner, "make_source", lambda *args, **kwargs: (source, {}))
    monkeypatch.setattr(runner, "validate", lambda *_args: None)
    monkeypatch.setattr(runner, "authored_hashes", lambda _source: {})

    with pytest.raises(CheckFailed, match="baseline failed"):
        suite.source("workspace")

    assert "workspace" not in suite.sources
    assert "workspace" not in suite.baselines


def test_keep_on_failure_records_and_retains_active_fortigate(tmp_path):
    from unittest.mock import Mock

    from runner import Suite

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "lab.clab.yml").write_text("name: frt-test-workspace\n")
    suite = object.__new__(Suite)
    suite.root = tmp_path
    suite.eclab = tmp_path / "eclab"
    suite.password = "test-only"
    suite.commands = Mock()
    suite.commands.run.side_effect = CheckFailed("deployment failed")
    suite.report = Report(tmp_path, "lean", [])
    suite.report.current = "lean-001"
    suite.active = []
    suite.preserved = []
    suite.keep_on_failure = True
    suite.catalog_added = False
    suite.journal = Mock()

    with pytest.raises(CheckFailed, match="deployment failed"):
        suite.deploy(workspace, source=True)

    assert len(suite.active) == 1
    assert suite.active[0] in suite.preserved
    assert suite.report.data["preserved_labs"] == [
        {
            "workspace": str(workspace.resolve()),
            "node": "fortigate",
            "container": "clab-frt-test-workspace-fortigate",
            "reason": "deployment failed",
        }
    ]
    suite.cleanup()
    suite.commands.run.assert_called_once()
    assert suite.active
    assert "preserved fortigate" in suite.report.data["cleanup"][0]


def test_source_templates_validate_pki_and_keep_literal_recursive_base(tmp_path):
    import yaml
    from engulf_clab_pki.catalog import bind_topology_requests, merge_catalogs

    for scope in ("workspace", "user"):
        source, additions = make_source(
            tmp_path, "test123", scope, "runtime-only-test-value", "fortigate:test"
        )
        assert not list(source.rglob("*.pyc"))
        topology = yaml.safe_load((source / "lab.clab.yml").read_text())
        assert uuid.UUID(topology["topology"]["nodes"]["fortigate"]["env"]["FOS_UUID"])
        assert (
            topology["topology"]["nodes"]["fortigate"]["env"][
                "FOS_EXIT_ON_BOOTSTRAP_ERROR"
            ]
            == "false"
        )
        assert "license" not in topology["topology"]["nodes"]["fortigate"]
        assert not any(
            key.endswith("LIC_CLAMP")
            for key in topology["topology"]["nodes"]["fortigate"]["env"]
        )
        catalog = merge_catalogs(
            {"version": 2, **additions},
            yaml.safe_load((source / "pki.yaml").read_text()),
        )
        bind_topology_requests(catalog, topology)
        image = topology["topology"]["nodes"]["base-build"]["image"]
        assert (source / "linux/Dockerfile").read_text().startswith(f"FROM {image}\n")
        assert (
            topology["topology"]["nodes"]["fortigate"]["image"] == "${FORTIGATE_IMAGE}"
        )
        assert (
            topology["topology"]["nodes"]["wan"]["image"]
            == "eclab.containers/wan-access"
        )
        assert {tuple(link["endpoints"]) for link in topology["topology"]["links"]} == {
            ("fortigate:eth1", "linux:eth1"),
            ("fortigate:eth2", "wan:eth1"),
        }
        assert "set mode dhcp" in (source / "fortigate.conf").read_text()
        assert WAN_IMAGE == "eclab.containers/wan-access:latest"


def test_normalization_changes_only_explicit_boundaries_and_aliases():
    original = {
        "path": "/source/lab/config",
        "similar": "/source/lab-other/config",
        "hash": "abc",
        "address": "198.18.77.1",
        "identity": "global/root",
        "name": "global/root-not-this",
    }
    copy_before = copy.deepcopy(original)
    actual = normalize(
        original, [("/source/lab", "<workspace>")], {"global/root": "local/root"}
    )
    assert actual == original | {"path": "<workspace>/config", "identity": "local/root"}
    assert original == copy_before
    assert normalize({"fingerprint": "a"}) != normalize({"fingerprint": "b"})


def test_fortigate_wan_probe_checks_default_route_effect():
    routes = "S* 0.0.0.0/0 [5/0] via 198.19.0.1, port3, 00:01:18, [1/0]\n"
    assert fortigate_default_route_uses(routes, "port3")
    assert not fortigate_default_route_uses(routes, "port1")
    assert not fortigate_default_route_uses("C 198.19.0.0/24 port3", "port3")


def test_guest_pki_probe_does_not_count_public_keys_as_private(tmp_path):
    projection = runpy.run_path(str(Path(__file__).parent / "fixtures/linux/probe.py"))[
        "projection"
    ]
    (tmp_path / "inventory.json").write_text(
        json.dumps(
            {
                "trusted_authorities": [],
                "requested_private_authorities": [],
                "issued_identities": [],
            }
        )
    )
    own = tmp_path / "issued/linux/local/client"
    own.mkdir(parents=True)
    (own / "private-key.pem").write_text("private test material")
    (own / "public-key.pem").write_text("public test material")
    authority = tmp_path / "authorities/effective/root/default"
    authority.mkdir(parents=True)
    (authority / "public-key.pem").write_text("public test material")

    result = projection(tmp_path)

    assert result["private_keys"] == ["issued/linux/local/client/private-key.pem"]
    assert result["permissions"] == {
        "issued/linux/local/client/private-key.pem": "0o644"
    }


@pytest.mark.parametrize(
    "kind,message",
    [
        ("removed-lean", "unrecognized arguments: --lean"),
        ("bad-passphrase", "PKI identity bundle authentication failed"),
        ("missing-binding", "unresolved frozen PKI bindings: root"),
        (
            "bad-binding",
            "PKI binding 'root' requires fingerprint abc; 'wrong' does not match",
        ),
        ("mode-conflict", "--offline not allowed with argument --eclab-with-runtime"),
        ("image-conflict", "--bundle-image requires --offline"),
        ("incomplete", "offline runtime is incomplete"),
        (
            "tool-mismatch",
            "recorded Containerlab differs and no safe repository is available",
        ),
    ],
)
def test_expected_failure_requires_diagnostic_and_positive_exit(kind, message):
    assert expected_failure(kind, 1, message)
    assert not expected_failure(kind, 0, message)
    assert not expected_failure(kind, -15, message)
    assert not expected_failure(kind, 1, "unrelated configuration error")


def test_cleanup_never_selects_similarly_named_workspaces_or_labs(tmp_path):
    assert owned_container({"containerlab": "frt-1"}, "frt-1")
    assert not owned_container({"containerlab": "frt-10"}, "frt-1")
    assert not owned_container({"name": "frt-1"}, "frt-1")


def test_catalog_cleanup_preserves_existing_and_concurrent_entries():
    existing = {"version": 2, "authorities": {"unrelated": {"lifetime": "persistent"}}}
    additions = {"authorities": {"frt-test": {"freeze": {"exportable": True}}}}
    catalog = merge_catalog(existing, additions)
    catalog["authorities"]["concurrent"] = {}
    assert merge_catalog(catalog, additions, remove=True) == {
        "version": 2,
        "authorities": {"unrelated": {"lifetime": "persistent"}, "concurrent": {}},
    }
    assert "frt-test" not in existing["authorities"]
    with pytest.raises(CheckFailed, match="already exists"):
        merge_catalog(catalog, additions)
    catalog["authorities"]["frt-test"] = {"changed": True}
    with pytest.raises(CheckFailed, match="refusing cleanup"):
        merge_catalog(catalog, additions, remove=True)


def test_reports_omit_known_secrets_pem_credentials_and_private_urls(tmp_path):
    report = Report(tmp_path, "lean", [])
    report.secrets = ["test-secret-value", "/private/pool"]
    text = report.sanitize(
        "-----BEGIN PRIVATE KEY-----\nmaterial\n-----END PRIVATE KEY-----\n"
        "a=test-secret-value\n/private/pool/file.lic\n"
        "https://user:password@example.test/simple\npassword=anything\n"
        "SSHPASS=probe-password\nset password cli-secret\n"
    )
    for secret in (
        "test-secret-value",
        "material",
        "/private/pool",
        "user:password",
        "anything",
        "probe-password",
        "cli-secret",
    ):
        assert secret not in text
    assert "passwordless sudo" in report.sanitize(
        "offline isolation requires passwordless sudo"
    )


def test_rewrite_archive_streams_untouched_members(tmp_path):
    source, target = tmp_path / "source.tar.gz", tmp_path / "modified.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        for name, data in (
            ("root/keep", b"large image stand-in"),
            ("root/change", b"before"),
            ("root/drop", b"omit"),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    rewrite_archive(
        source,
        target,
        lambda name, _: (
            b"after"
            if name.endswith("change")
            else False
            if name.endswith("drop")
            else None
        ),
    )
    with tarfile.open(target) as archive:
        assert archive.extractfile("root/keep").read() == b"large image stand-in"
        assert archive.extractfile("root/change").read() == b"after"
        assert "root/drop" not in archive.getnames()
