from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"


def test_distribution_is_not_a_plugin_and_excludes_requested_packages() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = tuple(project["dependencies"])
    assert not any(item.startswith("engulf-clab-all-plugins") for item in dependencies)
    assert not any(item.startswith("engulf-clab-wan") for item in dependencies)
    assert not any(item.startswith("engulf-clab-develop-eclab-lab") for item in dependencies)

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entry_points = pyproject["project"].get("entry-points", {})
    assert not any(name.startswith("engulf.plugins.") for name in entry_points)


def test_coverage_accounts_for_every_direct_runtime_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = {
        item.split(">", 1)[0].split("<", 1)[0].split("=", 1)[0]
        for item in project["dependencies"]
    }
    coverage = yaml.safe_load((BUNDLE / "coverage.yaml").read_text(encoding="utf-8"))
    covered = {
        entry["distribution"] for entry in coverage["plugins"].values()
    } | set(coverage["supporting_contracts"])
    assert dependencies - {"engulf-clab"} == covered


def test_coverage_names_every_topology_control() -> None:
    coverage = (BUNDLE / "coverage.yaml").read_text(encoding="utf-8")
    controls = {
        "ECLAB_VRNETLAB_TYPE",
        "ECLAB_DOCKERFILE",
        "ECLAB_DOCKER_CTX",
        "ECLAB_DOCKER_VAR_DEMO_RELEASE",
        "ECLAB_DOCKER_ARGS",
        "ECLAB_DOCKER_BASE_NODE",
        "ECLAB_IMAGE_ARCHIVE",
        "ECLAB_IMAGE_ARCHIVE_REF",
        "ECLAB_IMAGE_ARCHIVE_RELOAD",
        "ECLAB_IMAGE_PARAM_ROLE",
        "ECLAB_CONNECT_HOST",
        "ECLAB_DHCP_SUBNET",
        "ECLAB_DHCP_GATEWAY",
        "ECLAB_DHCP_POOL_START",
        "ECLAB_DHCP_POOL_END",
        "ECLAB_DHCP_DNS",
        "ECLAB_DHCP_LEASE_TIME",
        "ECLAB_PKI_MANIFEST",
        "ECLAB_PKI_MOUNT_TARGET",
        "FOS_UUID",
    }
    assert not {control for control in controls if control not in coverage}


def test_topology_uses_one_namespaced_bridge_parent_and_no_managed_wan() -> None:
    topology = yaml.safe_load((BUNDLE / "all-features.clab.yml").read_text(encoding="utf-8"))
    nodes = topology["topology"]["nodes"]
    assert "segments" in nodes
    for name in ("client-net|segments", "dmz-net|segments", "work-net|segments"):
        assert nodes[name]["kind"] == "bridge"
        assert nodes[name]["network-mode"] == "container:segments"
    assert nodes["real-wan"]["image"] == "eclab.containers/wan-access"
    assert all("ECLAB_DHCP_WAN" not in str(node) for node in nodes.values())


def test_fortigate_ports_and_link_endpoints_are_unique() -> None:
    topology = yaml.safe_load((BUNDLE / "all-features.clab.yml").read_text(encoding="utf-8"))
    endpoints = [endpoint for link in topology["topology"]["links"] for endpoint in link["endpoints"]]
    assert len(endpoints) == len(set(endpoints))
    assert not any(endpoint == "fgt:port1" for endpoint in endpoints)
    assert {"fgt:port2", "fgt:port3", "fgt:port4"}.issubset(endpoints)


def test_pki_includes_database_directory_and_responders() -> None:
    manifest = yaml.safe_load((BUNDLE / "pki.yaml").read_text(encoding="utf-8"))
    service_types = {value["type"] for value in manifest["services"].values()}
    assert {"ejbca", "mariadb", "directory", "crl", "ocsp", "administration"} == service_types
    assert manifest["services"]["certificate-database"]["node"] == "pki-db"
    assert manifest["services"]["crl-responder"]["node"] == "pki-crl"
    assert manifest["services"]["ocsp-responder"]["node"] == "pki-ocsp"


def test_bundle_contains_no_entitled_or_generated_material() -> None:
    forbidden_suffixes = {".qcow2", ".lic", ".license", ".licence", ".p12", ".jks"}
    assert not any(path.suffix.lower() in forbidden_suffixes for path in BUNDLE.rglob("*"))
    for path in BUNDLE.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"BEGIN PRIVATE KEY" not in data
            assert b"BEGIN CERTIFICATE" not in data
