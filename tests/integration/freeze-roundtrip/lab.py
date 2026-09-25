"""Wheel-only producer, real catalog edits, and generated private lab inputs."""

import importlib.metadata
import json
import os
import shlex
import shutil
import sys
import uuid
from pathlib import Path

import yaml
from support import CheckFailed, digest

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
IMAGE = "vrnetlab/fortinet_fortigateb:8.0.0"
WAN_IMAGE = "eclab.containers/wan-access:latest"
DEFAULT_FORTIGATE_ARCHIVE = Path(
    "/home/kchaniveckyga/Downloads/images/FGT_VM64_KVM-v8-build0230-FORTINET.deb.kvm.zip"
)


def build_environments(root, commands):
    wheels = root / "wheels"
    wheels.mkdir()
    packages = [
        REPOSITORY / "engulf-clab",
        *sorted((REPOSITORY / "plugins").glob("*/pyproject.toml")),
    ]
    packages = [
        path.parent if path.name == "pyproject.toml" else path for path in packages
    ]
    commands.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            wheels,
            *packages,
        ],
        timeout=900,
    )
    producer = root / "producer"
    commands.run([sys.executable, "-m", "venv", "--without-pip", producer])
    commands.run(
        [
            sys.executable,
            "-m",
            "pip",
            "--python",
            producer / "bin/python",
            "install",
            "--no-compile",
            "--find-links",
            wheels,
            f"pip=={importlib.metadata.version('pip')}",
            *sorted(wheels.glob("*.whl")),
        ],
        timeout=900,
    )
    commands.run([producer / "bin/python", "-m", "pip", "check"])
    # Freeze downloads exact versions. Make locally built unpublished versions
    # available without editable checkouts or relying on an index upload.
    listing = commands.run(
        [
            producer / "bin/python",
            "-c",
            "import importlib.metadata as m,json; print(json.dumps([d.metadata['Name']+'=='+d.version for d in m.distributions()]))",
        ],
        private=True,
    )
    lock = root / "producer.lock"
    lock.write_text("\n".join(sorted(json.loads(listing.stdout))) + "\n")
    commands.run(
        [
            producer / "bin/python",
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--find-links",
            wheels,
            "--dest",
            wheels,
            "-r",
            lock,
        ],
        timeout=900,
    )
    recipient = root / "recipient-tools"
    commands.run([sys.executable, "-m", "venv", "--without-pip", recipient])
    commands.run(
        [
            sys.executable,
            "-m",
            "pip",
            "--python",
            recipient / "bin/python",
            "install",
            "--no-compile",
            "--no-index",
            "--find-links",
            wheels,
            "-r",
            lock,
        ],
        timeout=600,
    )
    for environment in (producer, recipient):
        commands.run([environment / "bin/python", "-m", "pip", "check"])
        commands.run(
            [
                environment / "bin/python",
                "-c",
                """
import importlib.metadata as m, json
for d in m.distributions():
    direct = json.loads(d.read_text('direct_url.json') or '{}')
    assert not direct.get('dir_info', {}).get('editable'), d.metadata['Name']
    assert not direct.get('url', '').startswith('file:') or direct['url'].endswith('.whl'), d.metadata['Name']
""",
            ]
        )
    return producer, recipient, wheels


def user_plugins(environment):
    home = Path(environment.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return home / "engulf-clab" / "user"


def workspace_plugins(workspace, environment):
    state = user_plugins(environment).parent / "workspaces"
    for metadata in state.glob("*/workspace.json"):
        if json.loads(metadata.read_text()).get("root") == str(workspace.resolve()):
            return metadata.parent / "plugins"
    raise CheckFailed("workspace state not registered after deploy")


def make_source(root, run_id, scope, password, image, *, fos_uuid=None):
    source = root / "sources" / scope
    shutil.copytree(
        HERE / "fixtures", source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    authority = f"frt-{run_id}-root" if scope == "user" else "root"
    reference = f"global/{authority}" if scope == "user" else "local/root"
    for path in source.rglob("*"):
        if path.is_file():
            text = path.read_text()
            for marker, value in {
                "@RUN@": run_id,
                "@SCOPE@": scope,
                "@AUTHORITY@": reference,
                "@ADMIN_PASSWORD@": password,
                "@FOS_UUID@": fos_uuid
                or str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"engulf-clab-freeze-roundtrip:{run_id}:{scope}",
                    )
                ),
            }.items():
                text = text.replace(marker, value)
            path.write_text(text)
            path.chmod(0o600)
    certificate = {
        "issuer": reference,
        "algorithm": "rsa",
        "freeze": {"exportable": True},
        "lifetime": "persistent",
    }
    manifest = {
        "version": 2,
        "authorities": {
            "untrusted": {
                "subject": {"common_name": "untrusted"},
                "lifetime": "persistent",
                "freeze": {"exportable": True},
            }
        },
        "certificates": {
            "server": certificate
            | {
                "subject": {"common_name": "freeze-roundtrip.test"},
                "sans": {"dns": ["freeze-roundtrip.test"], "ip": ["198.18.77.1"]},
                "extended_key_usage": ["server_auth"],
            },
            "client": certificate
            | {
                "subject": {"common_name": "freeze-roundtrip-client"},
                "extended_key_usage": ["client_auth"],
            },
        },
    }
    root_definition = {
        "algorithm": "rsa",
        "subject": {"common_name": "freeze-roundtrip-root"},
        "lifetime": "persistent",
        "freeze": {"exportable": True},
    }
    if scope == "workspace":
        manifest["authorities"]["root"] = root_definition
    (source / "pki.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (source / "lab.env").write_text(
        f"FORTIGATE_IMAGE={image}\nROUNDTRIP_VALUE=roundtrip-v1\n"
    )
    (source / "lab.env").chmod(0o600)
    return source, {
        "authorities": {authority: root_definition}
    } if scope == "user" else {}


def edit_catalog(commands, eclab, additions_file, operation, cwd):
    # eclab validates staged YAML and checks the original digest before publish.
    editor = shlex.join(
        [
            str(Path(eclab).parent / "python"),
            str(HERE / "catalog_edit.py"),
            operation,
            str(additions_file),
        ]
    )
    commands.run(
        [eclab, "pki", "global", "edit"],
        cwd=cwd,
        env={"VISUAL": editor, "EDITOR": editor},
    )


def authored_hashes(source):
    names = [
        "lab.clab.yml",
        "fortigate.conf",
        "pki.yaml",
        "lab.env",
        "base/Dockerfile",
        "base/marker",
        "linux/Dockerfile",
        "linux/marker",
        "linux/probe.py",
    ]
    return {name: digest(source / name) for name in names}


def refresh(commands, eclab, root, discovery_environment=None):
    config = root / "discovery"
    config.mkdir(mode=0o700)
    commands.run([eclab, "--help"])
    commands.run([eclab, "--engulf-plugin-list"])
    commands.run([eclab, "freeze", "--help"])
    commands.run([eclab, "defrost", "--help"])
    commands.run([eclab, "--eclab-containers-help"])
    commands.run(
        [eclab, "install-develop-eclab-lab-skill", config],
        timeout=600,
        env=discovery_environment,
    )
    skill = config / "skills/develop-eclab-lab"
    # Re-read the refreshed entrypoint and pointer; never fall back to an older runtime.
    if not (skill / "SKILL.md").read_text():
        raise CheckFailed("empty refreshed runtime skill")
    pointer = json.loads((skill / "references/current.json").read_text())
    schemas = list(skill.glob("references/runtimes/*/clab.schema.json"))
    if len(schemas) != 1 or not pointer:
        raise CheckFailed("fresh runtime discovery must select one schema")
    return schemas[0]


def validate(source, schema):
    import jsonschema
    from engulf_clab_lab_parser import load_topology

    document = load_topology(source / "lab.clab.yml", os.environ)
    jsonschema.Draft7Validator(json.loads(schema.read_text())).validate(document)
    endpoints = [
        endpoint
        for link in document["topology"]["links"]
        for endpoint in link["endpoints"]
    ]
    if len(endpoints) != len(set(endpoints)) or any(
        endpoint.endswith(":eth0") for endpoint in endpoints
    ):
        raise CheckFailed("invalid fixture data-plane endpoints")
