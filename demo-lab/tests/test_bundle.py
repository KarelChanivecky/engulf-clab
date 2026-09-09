from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"


def test_distribution_is_not_a_plugin_and_excludes_nonportable_packages() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = tuple(project["dependencies"])
    excluded = (
        "engulf-clab-all-plugins",
        "engulf-clab-wan",
        "engulf-clab-ensure-vrnetlab",
        "engulf-clab-vrnetlab-build",
        "engulf-clab-license-pool",
        "engulf-clab-vrnetlab-fortigate-pki-injector",
        "engulf-clab-develop-eclab-lab",
    )
    assert not any(item.startswith(excluded) for item in dependencies)
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(
        name.startswith("engulf.plugins.")
        for name in pyproject["project"].get("entry-points", {})
    )


def test_coverage_accounts_for_every_direct_runtime_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = {
        item.split(">", 1)[0].split("<", 1)[0].split("=", 1)[0]
        for item in project["dependencies"]
    }
    coverage = yaml.safe_load((BUNDLE / "coverage.yaml").read_text(encoding="utf-8"))
    covered = {entry["distribution"] for entry in coverage["plugins"].values()} | set(
        coverage["supporting_contracts"]
    )
    assert dependencies - {"engulf-clab"} == covered


def test_coverage_names_every_topology_control() -> None:
    coverage = (BUNDLE / "coverage.yaml").read_text(encoding="utf-8")
    controls = {
        "ECLAB_DOCKERFILE", "ECLAB_DOCKER_CTX", "ECLAB_DOCKER_VAR_DEMO_RELEASE",
        "ECLAB_DOCKER_ARGS", "ECLAB_DOCKER_BASE_NODE", "ECLAB_IMAGE_ARCHIVE",
        "ECLAB_IMAGE_ARCHIVE_REF", "ECLAB_IMAGE_ARCHIVE_RELOAD", "ECLAB_IMAGE_PARAM_ROLE",
        "ECLAB_CONNECT_HOST", "ECLAB_CONNECT_HOST_7", "ECLAB_DHCP_SUBNET",
        "ECLAB_DHCP_GATEWAY", "ECLAB_DHCP_POOL_START", "ECLAB_DHCP_POOL_END",
        "ECLAB_DHCP_DNS", "ECLAB_DHCP_LEASE_TIME", "ECLAB_PKI_MANIFEST",
        "ECLAB_PKI_MOUNT_TARGET", "ECLAB_PKI_CERTIFICATES", "ECLAB_PKI_TRUST_MODE",
        "ECLAB_PKI_TRUST_INCLUDE", "ECLAB_PKI_IDENTITY_CURL", "ECLAB_PKI_IDENTITY_NGINX",
        "ECLAB_PKI_BROWSER_CLIENT_CERTS", "ECLAB_PKI_REQUIRED", "ECLAB_PKI_SYSTEM_TRUST",
    }
    assert not {control for control in controls if control not in coverage}


def test_topology_uses_linux_router_two_subnets_and_packaged_uplink() -> None:
    topology = yaml.safe_load((BUNDLE / "all-features.clab.yml").read_text(encoding="utf-8"))
    nodes = topology["topology"]["nodes"]
    assert "fgt" not in nodes and "fake-wan" not in nodes and "work-net|segments" not in nodes
    for name in ("client-net|segments", "dmz-net|segments"):
        assert nodes[name]["kind"] == "bridge"
        assert nodes[name]["network-mode"] == "container:segments"
    router = nodes["router"]
    assert router["kind"] == "linux"
    assert router["cap-add"] == ["NET_ADMIN"]
    assert router["sysctls"]["net.ipv4.ip_forward"] == 1
    assert router["env"]["ECLAB_IMAGE_PARAM_ROLE"] == "router"
    assert nodes["real-wan"]["image"] == "eclab.containers/wan-access"
    endpoints = [endpoint for link in topology["topology"]["links"] for endpoint in link["endpoints"]]
    assert {"router:eth1", "router:eth2", "router:eth3"}.issubset(endpoints)
    assert len(endpoints) == len(set(endpoints))
    segment_interfaces = [endpoint.split(":", 1)[1] for endpoint in endpoints if "|segments:" in endpoint]
    assert len(segment_interfaces) == len(set(segment_interfaces))


def test_router_configures_internal_routes_and_uplink_nat() -> None:
    entrypoint = (BUNDLE / "images/router/entrypoint.sh").read_text(encoding="utf-8")
    assert "10.10.10.1/24 dev eth1" in entrypoint
    assert "192.0.2.1/24 dev eth2" in entrypoint
    assert "udhcpc -i eth3" in entrypoint
    assert "-i eth1 -o eth2 -j ACCEPT" in entrypoint
    assert "-i eth2 -o eth1 -j ACCEPT" in entrypoint
    assert "-t nat -A POSTROUTING -o eth3 -j MASQUERADE" in entrypoint


def test_archive_image_installs_the_httpd_applet() -> None:
    dockerfile = (BUNDLE / "images/archive-source/Dockerfile").read_text(encoding="utf-8")
    assert "apk add --no-cache busybox-extras" in dockerfile
    assert 'CMD ["httpd", "-f", "-p", "8080", "-h", "/srv/www"]' in dockerfile


def test_linux_pki_consumers_cover_families_mtls_and_external_copy() -> None:
    topology = yaml.safe_load((BUNDLE / "all-features.clab.yml").read_text(encoding="utf-8"))
    nodes = topology["topology"]["nodes"]
    assert nodes["client-a"]["env"]["ECLAB_PKI_IDENTITY_CURL"] == "client-a-mtls"
    assert nodes["dmz-docker"]["env"]["ECLAB_PKI_IDENTITY_NGINX"] == "dmz-nginx-primary"
    assert nodes["dmz-fedora"]["env"]["ECLAB_PKI_IDENTITY_NGINX"] == "dmz-nginx-cross-signed"
    nginx = (BUNDLE / "images/dmz-server/nginx.conf").read_text(encoding="utf-8")
    assert "ssl_client_certificate /mnt/eclab/pki/trust/ca-bundle.pem" in nginx
    assert "ssl_verify_client on" in nginx
    assert "$ssl_client_verify" in nginx
    dockerfiles = [path.read_text(encoding="utf-8") for path in (BUNDLE / "images").glob("*/Dockerfile")]
    assert any("COPY --from=engulf-clab.pki-linux-debian/installer:latest" in text for text in dockerfiles)
    assert any("COPY --from=engulf-clab.pki-linux-fedora/installer:latest" in text for text in dockerfiles)
    client_commands = nodes["client-a"]["exec"]
    assert not any("printf" in command for command in client_commands)
    assert sum(" >> /etc/hosts" in command for command in client_commands) == 3


def test_pki_named_identities_roles_trust_and_cross_signing() -> None:
    topology = yaml.safe_load((BUNDLE / "all-features.clab.yml").read_text(encoding="utf-8"))
    nodes = topology["topology"]["nodes"]
    manifest = yaml.safe_load((BUNDLE / "pki.yaml").read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert manifest["profiles"]["tls-client"]["extended_key_usage"] == ["client_auth"]
    assert manifest["profiles"]["tls-server"]["extended_key_usage"] == ["server_auth"]
    assert manifest["authorities"]["issuing"]["variants"]["alternate-chain"]["issuer"] == "alternate-root"
    assert "deep-inspection" not in manifest["authorities"]
    assert "fgt-access-proxy" not in manifest["certificates"]
    assert manifest["certificates"]["dmz-nginx-primary"]["issuer"] == "issuing"
    primary = manifest["certificates"]["dmz-nginx-primary"]
    assert primary["aia"] and primary["crl_distribution_points"] and primary["extensions"]
    assert primary["freeze"] == {"exportable": True}
    assert manifest["certificates"]["dmz-nginx-cross-signed"]["issuer"] == "issuing/alternate-chain"
    assert nodes["client-a"]["env"]["ECLAB_PKI_CERTIFICATES"].split(",") == [
        "client-a-mtls", "client-a-secondary"
    ]
    assert nodes["client-b"]["env"]["ECLAB_PKI_TRUST_MODE"] == "none"
    assert nodes["client-b"]["env"]["ECLAB_PKI_TRUST_INCLUDE"] == "demo-root"


def test_pki_includes_database_directory_and_responders() -> None:
    manifest = yaml.safe_load((BUNDLE / "pki.yaml").read_text(encoding="utf-8"))
    service_types = {value["type"] for value in manifest["services"].values()}
    assert {"ejbca", "mariadb", "directory", "crl", "ocsp", "administration"} == service_types


def test_bundle_contains_no_entitled_generated_or_fortigate_material() -> None:
    forbidden_suffixes = {".qcow2", ".lic", ".license", ".licence", ".p12", ".jks"}
    assert not any(path.suffix.lower() in forbidden_suffixes for path in BUNDLE.rglob("*"))
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in BUNDLE.rglob("*") if path.is_file())
    assert "fortinet_fortigate" not in text
    assert "FOS_PKI_" not in text
    for path in BUNDLE.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"BEGIN PRIVATE KEY" not in data
            assert b"BEGIN CERTIFICATE" not in data


def test_runbook_inspects_by_lab_name_not_source_topology() -> None:
    runbook = (BUNDLE / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "inspect --name eclab-all-features" in runbook
    assert "inspect -t all-features.clab.yml" not in runbook
