#!/usr/bin/env python3
"""Opt-in freeze round-trip integration suite. Never imported by unit targets."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import signal
import stat
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from subprocess import SubprocessError

import yaml
from isolation import Offline, require_offline
from lab import (
    DEFAULT_FORTIGATE_ARCHIVE,
    REPOSITORY,
    WAN_IMAGE,
    authored_hashes,
    build_environments,
    edit_catalog,
    make_source,
    refresh,
    user_plugins,
    validate,
)
from matrix import cases, coverage
from probes import check_released, compare, docker, observe
from support import Blocked, CheckFailed, Commands, Report, digest, expected_failure


def rewrite_archive(source, target, transform):
    """Modify only a generated test archive, streaming large image members."""
    with tarfile.open(source) as src, tarfile.open(target, "w:gz") as dst:
        for member in src:
            stream = src.extractfile(member) if member.isfile() else None
            data = transform(member.name, stream) if stream is not None else None
            if data is False:
                continue
            if isinstance(data, bytes):
                member.size = len(data)
                stream = io.BytesIO(data)
            dst.addfile(member, stream)


class Suite:
    def __init__(self, root, mode, selected, report):
        self.root, self.mode, self.selected, self.report = root, mode, selected, report
        self.run_id = secrets.token_hex(5)
        self.image = f"freeze-roundtrip/fortigate:{self.run_id}"
        # The FortiOS launcher provides the ephemeral test node password.
        # Do not change it again in the later startup-config feature.
        self.password = "admin"
        self.passphrase = root / "pki-passphrase"
        self.passphrase.write_text(secrets.token_urlsafe(40))
        self.passphrase.chmod(0o600)
        self.report.secrets.append(self.passphrase.read_text())
        self.environment = dict(os.environ)
        # Keep completion and pip caches test-owned. License allocation is
        # intentionally absent from these lifecycle tests.
        for key in tuple(self.environment):
            if key.startswith(("ECLAB_LICENSE", "ECLAB_AUTO_LICENSE", "PYTHONPATH")):
                self.environment.pop(key)
        self.environment.update(
            XDG_CACHE_HOME=str(root / "cache"),
            PIP_NO_INPUT="1",
            CONTAINERLAB_UPDATE="0",
            VRNETLAB_UPDATE="0",
        )
        self.commands = Commands(report, self.environment)
        self.producer = self.recipient = None
        self.sources, self.baselines, self.archives = {}, {}, {}
        self.active = []
        self.preserved = []
        self.keep_on_failure = False
        self.catalog_added = False
        self.additions = root / "catalog-additions.json"
        self.authority = f"frt-{self.run_id}-root"
        (root / "archives").mkdir()
        (root / "restores").mkdir()
        (root / "unrelated").mkdir()

    def journal(self):
        (self.root / "ownership.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "uid": os.getuid(),
                    "root": str(self.root),
                    "run_id": self.run_id,
                    "active": self.active,
                    "catalog_added": self.catalog_added,
                    "producer": str(self.producer) if self.producer else None,
                },
                indent=2,
            )
        )

    def prerequisites(self):
        if os.geteuid() == 0:
            raise Blocked("eclab must run unprivileged")
        if sys.version_info < (3, 12):
            raise Blocked("Python 3.12 or newer required")
        for name in ("docker", "containerlab", "git", "openssl"):
            if not shutil.which(name):
                raise Blocked(f"required command missing: {name}")
        if self.commands.run(["docker", "info"], check=False, private=True).returncode:
            raise Blocked("Docker daemon inaccessible to the executing user")
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise Blocked("read/write KVM access required for FortiGate")
        archive = (
            Path(
                self.environment.get(
                    "FORTIGATE_ARCHIVE", str(DEFAULT_FORTIGATE_ARCHIVE)
                )
            )
            .expanduser()
            .resolve()
        )
        if not archive.is_file() or archive.suffix.lower() != ".zip":
            raise Blocked("FORTIGATE_ARCHIVE must name the local FortiGate .zip input")
        try:
            with zipfile.ZipFile(archive) as image_archive:
                qcow2 = [
                    item
                    for item in image_archive.infolist()
                    if not item.is_dir() and item.filename.lower().endswith(".qcow2")
                ]
        except zipfile.BadZipFile:
            raise Blocked(
                "FORTIGATE_ARCHIVE must be a valid FortiGate zip archive"
            ) from None
        if len(qcow2) != 1:
            raise Blocked("FORTIGATE_ARCHIVE must contain exactly one qcow2 image")
        self.image = f"freeze-roundtrip/fortigate:{self.run_id}"
        self.image_source = archive
        self.environment["REGISTRY"] = f"freeze-roundtrip/{self.run_id}/"
        self.owned_images = [
            self.image,
            f"freeze-roundtrip/{self.run_id}-linux:1",
            f"freeze-roundtrip/{self.run_id}-base:1",
            f"freeze-roundtrip/{self.run_id}/vr-fortios:fortios",
        ]
        # The provider extracts its sole qcow2 member into a private build stage.
        # The original archive remains outside the workspace and every freeze.
        self.environment["ECLAB_VRNETLAB_IMG_PATH"] = str(archive)
        self.report.secrets.append(str(archive))
        if self.mode == "offline":
            require_offline(self.commands)
        binary = Path(
            self.environment.get("CONTAINERLAB_BIN") or shutil.which("containerlab")
        ).resolve()
        if not (binary.stat().st_uid == 0 and binary.stat().st_mode & stat.S_ISUID):
            raise Blocked(
                "selected Containerlab needs supported sudo-less setup before real deployments"
            )
        self.environment["CONTAINERLAB_BIN"] = str(binary)
        self.binary = binary
        self.discovery_environment = {}
        # A system binary can identify a commit whose schema is unavailable on
        # the network. Prefer that exact Git object if a local checkout has it.
        if not self.environment.get("CONTAINERLAB_SCHEMA"):
            identity = json.loads(self.commands.run([binary, "version", "-j"]).stdout)
            revision = identity.get("commit") or identity.get("gitCommit")
            checkout_root = Path(
                self.environment.get(
                    "CONTAINERLAB_DIR", str(REPOSITORY.parent / "containerlab")
                )
            )
            if revision and (checkout_root / ".git").exists():
                schema = self.commands.run(
                    [
                        "git",
                        "-C",
                        checkout_root,
                        "show",
                        f"{revision}:schemas/clab.schema.json",
                    ],
                    check=False,
                    private=True,
                )
                if schema.returncode == 0:
                    path = self.root / "containerlab.schema.json"
                    path.write_text(schema.stdout)
                    self.environment["CONTAINERLAB_SCHEMA"] = str(path)
                    revision = self.commands.run(
                        ["git", "-C", checkout_root, "rev-parse", revision]
                    ).stdout.strip()
                    exact = self.root / "containerlab-source"
                    self.commands.run(["git", "init", exact])
                    self.commands.run(
                        [
                            "git",
                            "-C",
                            exact,
                            "fetch",
                            "--depth",
                            "1",
                            checkout_root,
                            revision,
                        ],
                        timeout=120,
                    )
                    self.commands.run(
                        ["git", "-C", exact, "checkout", "--detach", "FETCH_HEAD"]
                    )
                    self.discovery_environment = {
                        "CONTAINERLAB_BIN": "",
                        "CONTAINERLAB_DIR": str(exact),
                    }
        checkout = self.environment.get("VRNETLAB_DIR")
        if not checkout:
            candidates = [
                REPOSITORY.parent / "kvrnetlab",
                REPOSITORY.parent / "vrnetlab",
            ]
            checkout = next(
                (
                    str(path)
                    for path in candidates
                    if (path / "common/vrnetlab.py").is_file()
                ),
                "",
            )
        if not checkout or not (Path(checkout) / "common/vrnetlab.py").is_file():
            raise Blocked("set VRNETLAB_DIR to the exact producer vrnetlab checkout")
        self.environment["VRNETLAB_DIR"] = checkout
        self.commands.environment = self.environment

    def setup(self):
        self.prerequisites()
        self.producer, self.recipient, wheels = build_environments(
            self.root, self.commands
        )
        self.environment.update(
            PATH=str(self.producer / "bin") + os.pathsep + self.environment["PATH"],
            PIP_FIND_LINKS=str(wheels),
            PIP_NO_INDEX="1",
        )
        self.commands.environment = self.environment
        self.eclab = self.producer / "bin/eclab"
        self.recipient_eclab = self.recipient / "bin/eclab"
        self.commands.environment = self.environment
        try:
            self.schema = refresh(
                self.commands, self.eclab, self.root, self.discovery_environment
            )
        except CheckFailed:
            diagnostic = self.report.data["commands"][-1]["diagnostic"]
            if (
                "failed to fetch Containerlab schema" in diagnostic
                or "failed to fetch containerlab node-kind guidance" in diagnostic
            ):
                raise Blocked(
                    "exact Containerlab schema unavailable; provide CONTAINERLAB_SCHEMA for the selected binary commit"
                ) from None
            raise
        self.journal()

    def source(self, scope):
        if scope in self.sources:
            return self.sources[scope]
        source, additions = make_source(
            self.root,
            self.run_id,
            scope,
            self.password,
            self.image,
        )
        if additions:
            self.additions.write_text(json.dumps(additions))
            # Journal before publication, so an interrupt immediately afterwards
            # can safely retry exact-entry removal through the same editor.
            self.catalog_added = True
            self.journal()
            edit_catalog(self.commands, self.eclab, self.additions, "add", source)
        validate(source, self.schema)
        self.commands.run(
            [self.eclab, "pki", "effective", "-t", source / "lab.clab.yml"],
            cwd=source,
            private=True,
        )
        before = authored_hashes(source)
        baseline = self.deploy(source, source=True)
        self.sources[scope] = source
        self.baselines[scope] = baseline
        self.report.check(
            before == authored_hashes(source),
            "source authored files unchanged after baseline deployment and destroy",
        )
        return source

    def deploy(self, workspace, *, source=False, case=None, prefix=(), env=None):
        launcher = self.eclab if source else workspace / "run-eclab.sh"
        command = [
            launcher,
            "deploy",
            "-t",
            workspace / "lab.clab.yml",
        ]
        if case and case.focus in {"defaults", "unrelated-cwd"}:
            command = [launcher]
        current_env = env or {}
        cwd = (
            self.root / "unrelated"
            if case and case.focus == "unrelated-cwd"
            else workspace
        )
        record = {
            "workspace": str(workspace),
            "launcher": str(launcher),
            "source": source,
            "prefix": list(prefix),
            "env": env or {},
        }
        self.active.append(record)
        self.journal()
        try:
            result = self.commands.run(
                command, cwd=cwd, env=current_env, prefix=prefix, timeout=1200
            )
            if case and case.mode == "lean":
                self.report.check(
                    "missing (frozen" not in result.stdout
                    and "differs (frozen" not in result.stdout,
                    "lean launcher does not repeat defrost compatibility diagnostics",
                )
            baseline = observe(
                self.commands,
                workspace,
                self.password,
                prefix=prefix,
                env=current_env,
                readiness=int(os.environ.get("FREEZE_TEST_READINESS_SECONDS", "900")),
            )
        except BaseException as error:
            if self.keep_on_failure:
                self.preserve(record, error)
            else:
                self.destroy(record)
            raise
        if self.keep_on_failure and not source:
            # Keep the recipient running through equivalence assertions. If a
            # comparison fails, the outer cleanup recognizes this owned record
            # as intentionally preserved for inspection.
            return baseline
        self.destroy(record)
        return baseline

    def preserve(self, record, error):
        if record not in self.preserved:
            self.preserved.append(record)
        workspace = Path(record["workspace"])
        try:
            name = yaml.safe_load((workspace / "lab.clab.yml").read_text())["name"]
        except (OSError, KeyError, TypeError, yaml.YAMLError):
            name = workspace.name
        entry = {
            "workspace": str(workspace.resolve()),
            "node": "fortigate",
            "container": f"clab-{name}-fortigate",
            "reason": self.report.sanitize(error),
        }
        retained = self.report.data.setdefault("preserved_labs", [])
        if not any(item["workspace"] == entry["workspace"] for item in retained):
            retained.append(entry)
        self.journal()

    def destroy(self, record):
        workspace = Path(record["workspace"])
        # Never destroy --all or remove containers by a loose name prefix.
        result = self.commands.run(
            [
                record["launcher"],
                "destroy",
                "-t",
                workspace / "lab.clab.yml",
                "--cleanup",
            ],
            cwd=workspace,
            prefix=record["prefix"],
            env=record["env"],
            timeout=300,
            check=False,
        )
        if result.returncode:
            raise CheckFailed(
                "targeted destroy failed; ownership journal retained for recovery"
            )
        check_released(
            self.commands,
            workspace,
            prefix=record["prefix"],
            env=record["env"],
        )
        self.active.remove(record)
        self.journal()

    def archive(self, case):
        if case.archive_key in self.archives:
            return self.archives[case.archive_key]
        source = self.source(case.scope)
        before = authored_hashes(source)
        output = self.root / "archives" / f"{case.archive_key}.tar.gz"
        args = [self.eclab, "freeze", "-t", source / "lab.clab.yml", "--output", output]
        if case.focus == "defaults":
            args = [self.eclab, "freeze"]
            output = source / f"{source.name}.tar.gz"
        if case.mode == "runtime":
            args += ["--eclab-with-runtime"]
        if case.mode == "offline":
            args += ["--offline"]
        if case.image == "external":
            args += ["--external-image", self.image]
        if case.image.startswith("bundle-"):
            args += [
                "--bundle-image",
                self.image,
                "--bundle-image",
                f"freeze-roundtrip/{self.run_id}-linux:1",
                "--bundle-image",
                WAN_IMAGE,
            ]
        if case.encrypted:
            args += ["--include-pki-secrets", "--pki-passphrase-file", self.passphrase]
        self.commands.run(args, cwd=source, timeout=1800)
        self.report.check(
            before == authored_hashes(source),
            "freeze preserves all authored source bytes",
        )
        self.inspect_archive(output, case)
        self.archives[case.archive_key] = output
        return output

    def inspect_archive(self, archive, case):
        with tarfile.open(archive) as saved:
            names = ["/".join(Path(member.name).parts[1:]) for member in saved]
            prefix = saved.getnames()[0].split("/")[0]
            topology_bytes = saved.extractfile(f"{prefix}/lab.clab.yml").read()
            frozen_topology = yaml.safe_load(topology_bytes)
            metadata = frozen_topology["x-engulf-clab-freeze"]
            fortigate = frozen_topology["topology"]["nodes"]["fortigate"]
            self.report.check(
                metadata["mode"] == case.mode, "archive records selected mode"
            )
            self.report.check(
                "license" not in fortigate
                and not any(
                    key.endswith("LIC_CLAMP") for key in fortigate.get("env", {})
                ),
                "round-trip fixture uses no license inputs or clamps",
            )
            entries = json.load(saved.extractfile(f"{prefix}/images.freeze.json"))[
                "images"
            ]
            if case.mode == "lean":
                self.report.check(
                    not any(
                        name.split("/")[0]
                        in {
                            "wheelhouse",
                            "tools",
                            ".eclab-venv",
                            "requirements.freeze.txt",
                        }
                        for name in names
                    ),
                    "lean archive has no runtime artifacts",
                )
            if case.mode != "offline":
                self.report.check(
                    not any(entry.get("archive") for entry in entries),
                    "non-offline archive has no image archives",
                )
            if case.mode in {"runtime", "offline"}:
                self.report.check(
                    "requirements.freeze.txt" in names
                    and any(
                        name.startswith("wheelhouse/") and name.endswith(".whl")
                        for name in names
                    ),
                    "runtime archive has dependency lock and wheelhouse",
                )
                self.report.check(
                    bool(metadata["tools"]["containerlab"]["commit"]),
                    "runtime archive pins Containerlab identity",
                )
            if case.mode == "offline":
                self.report.check(
                    any(name.startswith(".eclab-venv/") for name in names)
                    and "tools/containerlab/bin/containerlab" in names,
                    "offline runtime and tools bundled",
                )
                self.report.check(
                    any(entry.get("archive") for entry in entries),
                    "offline image artifacts bundled",
                )
            for name in (
                "base/Dockerfile",
                "linux/Dockerfile",
                "base/marker",
                "linux/marker",
                "linux/probe.py",
                "fortigate.conf",
            ):
                original = self.sources[case.scope] / name
                self.report.check(
                    saved.extractfile(f"{prefix}/{name}").read()
                    == original.read_bytes(),
                    f"archive preserves {name}",
                )
            self.report.check(
                not any(
                    "private-key" in name or name.endswith(".lic") for name in names
                ),
                "archive contains no plaintext keys or license copies",
            )
            if case.encrypted:
                self.report.check(
                    ".eclab-pki-identities.enc" in names,
                    "exported identities encrypted",
                )
        return metadata

    def answers(self, archive):
        values = {"FORTIGATE_IMAGE": self.image, "ROUNDTRIP_VALUE": "roundtrip-v1"}
        with tarfile.open(archive) as saved:
            name = next(
                member.name
                for member in saved
                if member.name.endswith("/images.freeze.json")
            )
            entries = json.load(saved.extractfile(name))["images"]
            topology_name = next(
                member.name for member in saved if member.name.endswith("/lab.clab.yml")
            )
            topology = yaml.safe_load(saved.extractfile(topology_name))
        image = topology["topology"]["nodes"]["fortigate"]["image"]
        if image.startswith("${ECLAB_FREEZE_") and image.endswith("}"):
            values[image[2:-1]] = self.image
        for entry in entries:
            if entry.get("archive_variable"):
                variable = entry["archive_variable"]
                archive_input = entry.get("archive")
                if isinstance(archive_input, str) and archive_input:
                    values[variable] = archive_input
                    continue
                image = entry.get("image")
                if not isinstance(image, str) or not image:
                    raise CheckFailed(
                        "external image archive input has no image reference"
                    )
                image_inputs = self.root / "external-image-inputs"
                image_inputs.mkdir(mode=0o700, exist_ok=True)
                safe_name = hashlib.sha256(image.encode()).hexdigest()
                image_archive = image_inputs / f"{safe_name}.tar"
                if not image_archive.is_file():
                    self.commands.run(
                        ["docker", "image", "save", "--output", image_archive, image],
                        timeout=900,
                        private=True,
                    )
                    image_archive.chmod(0o600)
                values[variable] = str(image_archive)
        # Lean mode may preserve a rebuildable vrnetlab node while replacing
        # the invocation-provided appliance input with a recipient variable.
        for node in topology.get("topology", {}).get("nodes", {}).values():
            environment = node.get("env", {}) if isinstance(node, dict) else {}
            if not isinstance(environment, dict):
                continue
            for value in environment.values():
                if not (
                    isinstance(value, str)
                    and value.startswith("${ECLAB_FREEZE_")
                    and value.endswith("}")
                ):
                    continue
                variable = value[2:-1]
                if "_VRNETLAB_IMG_PATH_" in variable:
                    values[variable] = str(self.image_source)
                elif "_ARCHIVE_" in variable:
                    if variable not in values:
                        raise CheckFailed(
                            "frozen image archive placeholder is missing from the image manifest"
                        )
                elif "_IMAGE_" in variable:
                    values[variable] = self.image
        return values

    def restore(self, case, archive, *, prefix=(), env=None):
        parent = self.root / "restores" / case.id
        parent.mkdir()
        target = parent / (
            archive.name.removesuffix(".tar.gz") if case.focus == "defaults" else "lab"
        )
        values = self.answers(archive)
        environment = (env or {}).copy()
        args = [
            self.recipient_eclab,
            "defrost",
            archive,
            "--no-pki-prompt",
        ]
        if case.focus != "defaults":
            args += ["--into", target]
        if case.runtime == "deferred":
            args += ["--no-runtime"]
        if case.environment == "env":
            for key, value in values.items():
                args += ["--env", f"{key}={value}"]
        else:
            environment.update(values)
            if case.environment == "initialize":
                args += ["--skip-env-init"]
        if case.pki == "user-explicit":
            args += ["--pki-authority", f"{self.authority}=global/{self.authority}"]
        if case.encrypted:
            args += ["--pki-passphrase-file", self.passphrase]
        if case.image.endswith("-load"):
            args += ["--load-images"]
        elif case.image.endswith("-explicit"):
            args += ["--no-images"]
        self.commands.run(
            args, cwd=parent, env=environment, prefix=prefix, timeout=1200
        )
        if case.destination == "force":
            (target / "force-sentinel").write_text("previous restore")
            self.commands.run(
                [*args, "--force"],
                cwd=parent,
                env=environment,
                prefix=prefix,
                timeout=1200,
            )
            self.report.check(
                not (target / "force-sentinel").exists(),
                "force replaces a recognized defrost destination",
            )
        if case.environment == "initialize":
            self.report.check(
                not (target / "lab.env").exists(),
                "skip-env-init leaves no recipient environment file",
            )
            self.commands.run(
                [target / "initialize-env.sh"],
                cwd=parent,
                env=environment,
                prefix=prefix,
            )
        if (target / "lab.env").exists():
            self.report.check(
                stat.S_IMODE((target / "lab.env").stat().st_mode) == 0o600,
                "recipient environment file is private",
            )
        if case.mode == "runtime" and case.runtime == "deferred":
            self.report.check(
                not (target / ".eclab-venv").exists(),
                "no-runtime defers environment preparation",
            )
        if case.image.endswith("-explicit"):
            entries = json.loads((target / "images.freeze.json").read_text())["images"]
            for entry in entries:
                if entry.get("archive"):
                    docker(
                        self.commands,
                        ["load", "-i", target / entry["archive"]],
                        prefix=prefix,
                        env=environment,
                        timeout=900,
                    )
                    if entry.get("image_id"):
                        docker(
                            self.commands,
                            ["tag", entry["image_id"], entry["image"]],
                            prefix=prefix,
                            env=environment,
                        )
        return target

    def success(self, case):
        archive = self.archive(case)
        offline = None
        prefix, environment = (), {}
        # Exported user material must stand on its own. Remove only our catalog
        # declaration during recipient execution, retaining its owned material
        # for subsequent automatic-binding cases.
        exported_user = case.pki == "user-export"
        if exported_user:
            edit_catalog(self.commands, self.eclab, self.additions, "remove", self.root)
        try:
            if case.mode == "offline":
                hidden = [
                    self.producer,
                    self.root / "wheels",
                    self.root / "cache",
                    self.root / "sources",
                    self.root / "containerlab-source",
                    REPOSITORY,
                    Path(self.environment["VRNETLAB_DIR"]),
                    self.binary,
                    Path.home() / ".cache",
                ]
                offline = Offline(
                    self.root / f"isolation-{case.id}", self.commands, hidden
                )
                offline.start()
                prefix, environment = offline.prefix, offline.environment
                # Recipient has independent host tooling for defrost. PATH and
                # runtime pins cannot reach a hidden producer environment.
                environment |= {
                    "PATH": f"{self.recipient}/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                    "PIP_NO_INDEX": "1",
                    "PIP_FIND_LINKS": "",
                    "CONTAINERLAB_BIN": "",
                    "VRNETLAB_DIR": "",
                    "CONTAINERLAB_SCHEMA": "",
                }
            else:
                environment["PATH"] = (
                    str(self.recipient / "bin") + os.pathsep + self.environment["PATH"]
                )
            target = self.restore(case, archive, prefix=prefix, env=environment)
            if offline:
                # Supported setup is applied only to the test-owned bundled binary.
                owned_binary = target / "tools/containerlab/bin/containerlab"
                self.commands.run(
                    [
                        self.recipient_eclab,
                        "sudoless",
                        "--eclab-containerlab-bin",
                        owned_binary,
                    ]
                )
                environment["CONTAINERLAB_BIN"] = str(owned_binary)
            restored = self.deploy(target, case=case, prefix=prefix, env=environment)
            compare(
                self.report, self.baselines[case.scope], restored, case, self.authority
            )
            for name in (
                "base/Dockerfile",
                "linux/Dockerfile",
                "base/marker",
                "linux/marker",
                "linux/probe.py",
                "fortigate.conf",
            ):
                self.report.check(
                    digest(target / name) == digest(self.sources[case.scope] / name),
                    f"restored authored {name} unchanged",
                )
            if case.mode == "runtime":
                self.report.check(
                    (target / ".eclab-venv/bin/eclab").is_file()
                    and (target / ".eclab-freeze.env").is_file(),
                    "launcher uses prepared pinned runtime",
                )
            if self.keep_on_failure and self.active:
                self.destroy(self.active[-1])
        finally:
            if offline and not (self.keep_on_failure and self.active):
                offline.close()
            if exported_user:
                edit_catalog(
                    self.commands, self.eclab, self.additions, "add", self.root
                )

    def focused(self, case):
        kind = case.focus
        if kind in {"defaults", "unrelated-cwd"}:
            if kind == "defaults":
                self.archives.pop(case.archive_key, None)
            return self.success(case)
        source = self.source("user" if "binding" in kind else "workspace")
        target = self.root / "restores" / case.id
        common = [
            self.eclab,
            "freeze",
            "-t",
            source / "lab.clab.yml",
            "--output",
            self.root / "archives" / f"{case.id}.tar.gz",
        ]
        if kind in {"removed-lean", "mode-conflict", "image-conflict"}:
            flags = {
                "removed-lean": ["--lean"],
                "mode-conflict": ["--offline", "--eclab-with-runtime"],
                "image-conflict": ["--offline", "--external-image", self.image]
                if case.mode == "offline"
                else ["--bundle-image", self.image],
            }
            result = self.commands.run([*common, *flags[kind]], cwd=source, check=False)
            self.report.check(
                expected_failure(kind, result.returncode, result.stdout),
                f"expected {kind} diagnostic",
            )
            check_released(self.commands, source)
            return
        archive_case = replace(
            case,
            pki="user-auto"
            if "binding" in kind
            else "workspace-export"
            if kind == "bad-passphrase"
            else "workspace-regenerate",
            focus="",
        )
        archive = self.archive(archive_case)
        if kind in {"incomplete", "tool-mismatch", "warnings"}:
            changed = self.root / "archives" / f"{case.id}.tar.gz"

            def transform(name, stream):
                if kind == "incomplete" and "/wheelhouse/" in name:
                    return False
                if kind == "warnings" and name.endswith("/packages.freeze.txt"):
                    return stream.read() + b"freeze-roundtrip-missing-package==0.0.0\n"
                if kind == "tool-mismatch" and name.endswith("/lab.clab.yml"):
                    doc = yaml.safe_load(stream)
                    tools = doc["x-engulf-clab-freeze"]["tools"]
                    tools["containerlab"] = {
                        "version": "0.0.0-test",
                        "commit": "bad000000",
                    }
                    return yaml.safe_dump(doc).encode()
                return None

            rewrite_archive(archive, changed, transform)
            archive = changed
        args = [
            self.recipient_eclab,
            "defrost",
            archive,
            "--into",
            target,
            "--no-pki-prompt",
        ]
        for key, value in self.answers(archive).items():
            args += ["--env", f"{key}={value}"]
        environment = {}
        if kind == "bad-passphrase":
            wrong = self.root / "wrong-passphrase"
            wrong.write_text(secrets.token_urlsafe(30))
            wrong.chmod(0o600)
            self.report.secrets.append(wrong.read_text())
            args += ["--pki-passphrase-file", wrong]
        if kind == "bad-binding":
            args += [
                "--pki-authority",
                f"{self.authority}=global/nonexistent-roundtrip-authority",
            ]
        if kind == "missing-binding":
            environment["XDG_STATE_HOME"] = str(self.root / "empty-recipient-state")
        if kind == "warnings":
            self.commands.run(args)
            warning = target / "FREEZE-WARNINGS.txt"
            first = warning.read_text()
            self.report.check(
                first.count("freeze-roundtrip-missing-package") == 1,
                "lean defrost persists one compatibility warning",
            )
            warning.write_text(first + "sentinel-old-warning\n")
            self.commands.run([*args, "--force"])
            self.report.check(
                warning.read_text() == first,
                "force regenerates lean warnings from archive",
            )
            output = self.commands.run(
                [target / "run-eclab.sh", "--help"],
                env={
                    "PATH": str(self.recipient / "bin")
                    + os.pathsep
                    + self.environment["PATH"]
                },
            ).stdout
            self.report.check(
                "freeze-roundtrip-missing-package" not in output,
                "launcher does not repeat lean warnings",
            )
            check_released(self.commands, target)
            return
        if kind in {"missing-binding", "missing-image"}:
            self.commands.run([*args, "--no-runtime"], env=environment)
            if kind == "missing-image":
                doc = yaml.safe_load((target / "lab.clab.yml").read_text())
                doc["topology"]["nodes"]["fortigate"].setdefault("env", {})[
                    "ECLAB_VRNETLAB_IMG_PATH"
                ] = str(target / "missing-image.zip")
                (target / "lab.clab.yml").write_text(yaml.safe_dump(doc))
            result = self.commands.run(
                [
                    target / "run-eclab.sh",
                    "deploy",
                    "-t",
                    target / "lab.clab.yml",
                ],
                env=environment,
                cwd=target,
                timeout=600,
                check=False,
            )
        else:
            result = self.commands.run(args, env=environment, timeout=600, check=False)
        self.report.check(
            expected_failure(kind, result.returncode, result.stdout),
            f"expected {kind} diagnostic",
        )
        if (target / "lab.clab.yml").exists():
            check_released(self.commands, target)
        else:
            check_released(self.commands, source)

    def cleanup(self):
        errors = []
        for record in list(reversed(self.active)):
            if record in self.preserved:
                continue
            try:
                self.destroy(record)
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                SubprocessError,
            ) as error:
                errors.append(self.report.sanitize(error))
        if self.catalog_added and not self.active:
            try:
                edit_catalog(
                    self.commands, self.eclab, self.additions, "remove", self.root
                )
                # Only this run's uniquely named authority subtree is owned.
                owned = (
                    user_plugins(self.environment)
                    / "engulf_clab.pki/pki/authorities"
                    / self.authority
                )
                if owned.is_symlink():
                    raise CheckFailed(
                        "test authority state unexpectedly became a symlink"
                    )
                if owned.is_dir():
                    shutil.rmtree(owned)
                self.catalog_added = False
                self.journal()
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                SubprocessError,
            ) as error:
                errors.append(self.report.sanitize(error))
        if not self.active:
            for image in getattr(self, "owned_images", []):
                present = docker(
                    self.commands,
                    ["image", "inspect", image],
                    check=False,
                    private=True,
                )
                if present.returncode == 0:
                    removed = docker(
                        self.commands,
                        ["image", "rm", image],
                        check=False,
                        private=True,
                    )
                    if removed.returncode:
                        errors.append(f"could not remove test-owned image {image}")
        preserved = self.report.data.get("preserved_labs", [])
        notes = errors + [
            f"preserved {item['node']} at {item['workspace']} for debugging"
            for item in preserved
        ]
        self.report.data["cleanup"] = notes or [
            "owned labs, catalog entries, and test images released"
        ]
        return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("lean", "runtime", "offline"))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--case", action="append", default=[], metavar="ID")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--keep-on-failure",
        action="store_true",
        help="retain the active lab and its test-owned resources after a failure",
    )
    args = parser.parse_args()
    selected = cases(args.mode)
    if args.case:
        unknown = set(args.case) - {case.id for case in selected}
        if unknown:
            parser.error("unknown case IDs: " + ", ".join(sorted(unknown)))
        selected = [case for case in selected if case.id in args.case]
    if args.list:
        print(
            json.dumps(
                {
                    "cases": [case.public() for case in selected],
                    "coverage": coverage(args.mode, selected),
                },
                indent=2,
            )
        )
        return 0
    os.umask(0o077)
    root = args.work_dir or Path(
        tempfile.mkdtemp(prefix=f"freeze-roundtrip-{args.mode}-")
    )
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        parser.error(
            "--work-dir must be an empty, nonsymlink directory; retain old runs for recovery"
        )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve()
    root.chmod(0o700)
    print(f"Artifacts: {root}", flush=True)
    report = Report(root, args.mode, [case.public() for case in selected])
    report.data["planned_coverage"] = coverage(args.mode, selected)
    suite = Suite(root, args.mode, selected, report)
    suite.keep_on_failure = args.keep_on_failure

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    passed = []
    stop_reason = None
    try:
        suite.setup()
        for case in selected:
            report.current = case.id
            print(f"[{case.id}] starting", flush=True)
            started = time.monotonic()
            try:
                suite.focused(case) if case.focus else suite.success(case)
            except (CheckFailed, Blocked) as error:
                if suite.keep_on_failure and suite.active:
                    suite.preserve(suite.active[-1], error)
                status = "blocked" if isinstance(error, Blocked) else "failed"
                report.data["cases"].append(
                    {
                        "id": case.id,
                        "status": status,
                        "reason": report.sanitize(error),
                        "seconds": time.monotonic() - started,
                    }
                )
                if suite.active:
                    if suite.keep_on_failure:
                        stop_reason = "active lab retained for user debugging"
                        report.write()
                        break
                    raise CheckFailed(
                        "cleanup incomplete; stopping further deployments"
                    )
                if case.scope not in suite.sources:
                    stop_reason = (
                        f"baseline source lab for scope {case.scope} did not complete"
                    )
                    break
            else:
                passed.append(case)
                report.data["cases"].append(
                    {
                        "id": case.id,
                        "status": "passed",
                        "seconds": time.monotonic() - started,
                    }
                )
            report.write()
    except Blocked as error:
        if suite.keep_on_failure:
            for record in suite.active:
                suite.preserve(record, error)
        report.data["blockers"] = [report.sanitize(error)]
    except KeyboardInterrupt:
        if suite.keep_on_failure:
            for record in suite.active:
                suite.preserve(record, "interrupted during deployment")
        report.data["blockers"] = [
            "interrupted; active deployment retained for debugging"
            if suite.keep_on_failure and suite.preserved
            else "interrupted; targeted cleanup attempted"
        ]
    except (OSError, RuntimeError, ValueError, TypeError, SubprocessError) as error:
        if suite.keep_on_failure:
            for record in suite.active:
                suite.preserve(record, error)
        report.data["setup_failure"] = report.sanitize(
            f"{type(error).__name__}: {error}"
        )
    finally:
        cleanup_errors = suite.cleanup()
        done = {case["id"] for case in report.data["cases"]}
        for case in selected:
            if case.id not in done:
                report.data["cases"].append(
                    {
                        "id": case.id,
                        "status": "blocked",
                        "reason": stop_reason or "setup or earlier cleanup incomplete",
                    }
                )
        statuses = {case["status"] for case in report.data["cases"]}
        report.data["status"] = (
            "failed"
            if "failed" in statuses or cleanup_errors or "setup_failure" in report.data
            else "blocked"
            if "blocked" in statuses
            else "passed"
        )
        report.data["passed_coverage"] = coverage(args.mode, passed)
        report.write()
    print(f"{report.data['status']}: {root / 'summary.txt'}", flush=True)
    for lab in report.data.get("preserved_labs", []):
        print(
            f"Preserved lab: {lab['workspace']} | node {lab['node']} | "
            f"container {lab['container']}",
            flush=True,
        )
    return {"passed": 0, "failed": 1, "blocked": 2}[report.data["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
