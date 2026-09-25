"""Public runtime observations and strict, documented equivalence checks."""

import json
import re
import runpy
import time
from pathlib import Path

import yaml
from lab import HERE
from support import (
    CheckFailed,
    digest,
    normalize,
    owned_container,
)


def lab_name(workspace):
    return yaml.safe_load((workspace / "lab.clab.yml").read_text())["name"]


def docker(commands, arguments, *, prefix=(), env=None, **options):
    return commands.run(["docker", *arguments], prefix=prefix, env=env, **options)


def fortigate_default_route_uses(output, interface):
    return any(
        re.search(r"\b0\.0\.0\.0/0\b", line)
        and re.search(rf"\b{re.escape(interface)}\b", line)
        for line in output.splitlines()
    )


def container_ids(commands, name, prefix=(), env=None):
    result = docker(
        commands,
        ["ps", "-aq", "--filter", f"label=containerlab={name}"],
        prefix=prefix,
        env=env,
    )
    ids = result.stdout.split()
    if not ids:
        return []
    inspected = json.loads(
        docker(commands, ["inspect", *ids], prefix=prefix, env=env, private=True).stdout
    )
    if any(
        not owned_container(item["Config"].get("Labels", {}), name)
        for item in inspected
    ):
        raise CheckFailed("Docker filter returned a container not owned by this lab")
    return ids


def check_released(commands, workspace, *, prefix=(), env=None):
    report = commands.report
    report.check(
        not container_ids(commands, lab_name(workspace), prefix, env),
        "lab containers released",
    )


def effective(workspace, inspection):
    from engulf_clab_lab_parser import effective_nodes

    paths = list(workspace.glob(".engulf-clab-lab-*.clab.yml"))
    if len(paths) != 1:
        raise CheckFailed("deploy must retain exactly one effective writer topology")
    document = yaml.safe_load(paths[0].read_text())
    result = {"links": document["topology"]["links"], "nodes": {}}
    for node in effective_nodes(document):
        data = node.data
        environment = data.get("env", {})
        # Image recipe controls are compared through their resulting image and
        # startup behavior, not generated workspace paths.
        selected = {
            key: value
            for key, value in environment.items()
            if key in {"ROUNDTRIP_VALUE", "ECLAB_PKI_ROOT", "ECLAB_PKI_REQUIRED"}
        }
        result["nodes"][node.name] = {
            "kind": data["kind"],
            "image": data["image"],
            "env": selected,
            "exec": data.get("exec", []),
        }
        if "startup-config" in data:
            path = Path(data["startup-config"])
            if not path.is_absolute():
                path = workspace / path
            result["nodes"][node.name]["startup_sha256"] = digest(path)
    return result


def observe(
    commands,
    workspace,
    password,
    *,
    prefix=(),
    env=None,
    readiness=900,
):
    report = commands.report
    name = lab_name(workspace)
    linux, fortigate, wan = (
        f"clab-{name}-linux",
        f"clab-{name}-fortigate",
        f"clab-{name}-wan",
    )
    deadline = time.monotonic() + readiness
    while True:
        response = docker(
            commands,
            ["inspect", fortigate],
            prefix=prefix,
            env=env,
            check=False,
            private=True,
        )
        items = json.loads(response.stdout) if response.returncode == 0 else []
        if items and items[0]["State"].get("Health", {}).get("Status") == "healthy":
            break
        if items and items[0]["State"]["Status"] in {"dead", "exited"}:
            logs = docker(
                commands,
                ["logs", "--tail", "250", items[0]["Id"]],
                prefix=prefix,
                env=env,
                check=False,
                private=True,
            ).stdout
            directory = report.root / "private-diagnostics"
            directory.mkdir(mode=0o700, exist_ok=True)
            logfile = directory / f"{report.current}-fortigate.log"
            logfile.write_text(logs)
            logfile.chmod(0o600)
            clues = [
                line
                for line in logs.splitlines()
                if re.search(
                    r"error|failed|fatal",
                    line,
                    re.IGNORECASE,
                )
            ]
            summary = report.sanitize("\n".join(clues[-8:]))
            detail = f"; startup detail: {summary}" if summary else ""
            raise CheckFailed(
                f"FortiGate exited during bounded readiness polling{detail}"
            )
        if time.monotonic() >= deadline:
            raise CheckFailed("FortiGate readiness deadline exceeded")
        print(f"[{report.current}] waiting for FortiGate health", flush=True)
        time.sleep(15)
    inspections = json.loads(
        docker(
            commands,
            ["inspect", linux, fortigate, wan],
            prefix=prefix,
            env=env,
            private=True,
        ).stdout
    )
    report.check(
        inspections[2]["State"].get("Health", {}).get("Status") == "healthy",
        "WAN connector is healthy with DHCP and NAT ready",
    )
    report.check(
        len(container_ids(commands, name, prefix, env)) == 3,
        "exactly three runtime nodes; build-only base omitted",
    )
    docker(
        commands,
        ["exec", linux, "ping", "-c", "3", "-W", "3", "198.18.77.1"],
        prefix=prefix,
        env=env,
    )
    ssh = [
        "exec",
        "-e",
        f"SSHPASS={password}",
        linux,
        "sshpass",
        "-e",
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=10",
        "admin@198.18.77.1",
    ]
    interfaces = docker(
        commands,
        [*ssh, "show system interface port2"],
        prefix=prefix,
        env=env,
        private=True,
    ).stdout
    report.check(
        "198.18.77.1 255.255.255.0" in interfaces, "FortiGate port2 address preserved"
    )
    report.check(
        all(word in interfaces for word in ("ping", "https", "ssh")),
        "FortiGate port2 management services configured",
    )
    wan_interface = docker(
        commands,
        [*ssh, "show system interface port3"],
        prefix=prefix,
        env=env,
        private=True,
    ).stdout
    routes = docker(
        commands,
        [*ssh, "get router info routing-table all"],
        prefix=prefix,
        env=env,
        private=True,
    ).stdout
    default_via_wan = fortigate_default_route_uses(routes, "port3")
    report.check(
        "set mode dhcp" in wan_interface and default_via_wan,
        "FortiGate port3 uses the WAN connector for DHCP and its default route",
    )
    guest = json.loads(
        docker(
            commands,
            ["exec", linux, "python3", "/roundtrip-probe.py"],
            prefix=prefix,
            env=env,
            private=True,
        ).stdout
    )
    report.check(
        guest["markers"] == ["freeze-roundtrip-base-v1", "freeze-roundtrip-linux-v1"],
        "recursive build content markers preserved",
    )
    report.check(guest["value"] == "roundtrip-v1", "recipient environment value active")
    report.check(
        guest["untrusted_rejected"], "HTTPS rejects explicitly excluded authority"
    )
    code = docker(
        commands,
        [
            "exec",
            linux,
            "curl",
            "--silent",
            "--show-error",
            "--noproxy",
            "*",
            "--cacert",
            "/mnt/eclab/pki/trust/ca-bundle.pem",
            "--resolve",
            "freeze-roundtrip.test:443:198.18.77.1",
            "--max-time",
            "15",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "https://freeze-roundtrip.test/",
        ],
        prefix=prefix,
        env=env,
    ).stdout
    report.check(
        code in {"200", "301", "302", "303"}, "FortiGate HTTPS verified from Linux"
    )
    project = runpy.run_path(str(HERE / "fixtures/linux/probe.py"))["projection"]
    projections = {}
    for node, item in zip(("linux", "fortigate"), inspections[:2]):
        mounts = [
            mount
            for mount in item["Mounts"]
            if mount["Destination"] == "/mnt/eclab/pki"
        ]
        report.check(
            len(mounts) == 1 and not mounts[0]["RW"],
            f"{node} has a read-only authorized PKI view",
        )
        projection = project(Path(mounts[0]["Source"]))
        report.check(
            len(projection["private_keys"]) == 1
            and projection["private_keys"][0].startswith(f"issued/{node}/"),
            f"{node} exposes only its own leaf private key",
        )
        report.check(
            set(projection["permissions"].values()) == {"0o600"},
            f"{node} private-key modes are 0600",
        )
        report.check(
            all(projection["chains"].values()),
            f"{node} leaf chains validate against selected trust",
        )
        projections[node] = projection
    server = projections["fortigate"]["selected"]["issued_identities"][0]["certificate"]
    report.check(
        server["fingerprint"] == guest["https_fingerprint"],
        "HTTPS serves the injected certificate",
    )
    image_info = json.loads(
        docker(
            commands,
            ["image", "inspect", inspections[0]["Image"]],
            prefix=prefix,
            env=env,
            private=True,
        ).stdout
    )[0]
    report.check(
        image_info["Config"]["Entrypoint"] == ["/opt/eclab-pki/entrypoint", "--"],
        "Linux preserves packaged PKI entrypoint",
    )
    return {
        "topology": effective(workspace, inspections),
        "pki": projections,
        "image_ids": {
            node: item["Image"]
            for node, item in zip(("linux", "fortigate"), inspections)
        },
        "linux_config": {
            key: image_info["Config"].get(key)
            for key in ("Entrypoint", "Cmd", "Env", "Labels", "User", "WorkingDir")
        },
        "markers": guest["markers"],
        "http_status": code,
    }


def compare(report, baseline, restored, case, authority):
    report.check(
        baseline["topology"] == restored["topology"],
        "effective nodes, links, startup config and relevant environment equivalent",
    )
    for key in ("linux_config", "markers", "http_status"):
        report.check(baseline[key] == restored[key], f"equivalent {key}")
    report.check(
        baseline["image_ids"]["fortigate"] == restored["image_ids"]["fortigate"],
        "FortiGate image identity unchanged",
    )
    if case.mode == "offline":
        report.check(
            baseline["image_ids"] == restored["image_ids"],
            "bundled images preserve exact identity",
        )
    aliases = (
        {f"global/{authority}": f"local/{authority}"}
        if case.pki == "user-export"
        else {}
    )
    left = normalize(baseline["pki"], aliases=aliases)
    right = normalize(restored["pki"], aliases=aliases)
    if not case.encrypted:
        # Only regenerated certificate fingerprints may change. Subjects, SANs,
        # EKUs, key usage, issuer, chain validation, trust, key exposure remain.
        for record in (left, right):
            for node in record.values():
                for entries in node["selected"].values():
                    for entry in entries:
                        entry["certificate"].pop("fingerprint")
    report.check(
        left == right,
        "PKI projections equivalent"
        + (
            " with exact exported fingerprints"
            if case.encrypted
            else " with regenerated identity fingerprints excluded"
        ),
    )
