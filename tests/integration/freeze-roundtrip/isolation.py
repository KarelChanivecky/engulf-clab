"""Disposable daemon in a network/mount namespace; requires passwordless sudo."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from support import Blocked, CheckFailed


class Offline:
    def __init__(self, root, commands, hidden):
        self.root, self.commands, self.hidden = root, commands, hidden
        self.process = None
        self.prefix = ()
        self.environment = {}

    def start(self):
        self.root.mkdir(mode=0o700)
        helper = self.root / "host.py"
        shutil.copyfile(Path(__file__).with_name("offline_host.py"), helper)
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "root": str(self.root),
                    "uid": os.getuid(),
                    "gid": os.getgid(),
                    "hidden": [str(p) for p in self.hidden if p.exists()],
                }
            )
        )
        config.chmod(0o600)
        self.log = (self.root / "supervisor.log").open("w")
        self.process = subprocess.Popen(
            [
                "sudo",
                "-n",
                "unshare",
                "--mount",
                "--net",
                "--",
                sys.executable,
                str(helper),
                str(config),
            ],
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 45
        while not (self.root / "ready.json").exists():
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise Blocked(
                    "isolated Docker daemon did not become ready; inspect private supervisor.log"
                )
            time.sleep(0.2)
        pid = json.loads((self.root / "ready.json").read_text())["pid"]
        self.prefix = (
            "sudo",
            "-n",
            "nsenter",
            "--target",
            str(pid),
            "--mount",
            "--net",
            "--",
            "setpriv",
            f"--reuid={os.getuid()}",
            f"--regid={os.getgid()}",
            "--init-groups",
            "--",
        )
        self.environment = {"DOCKER_HOST": f"unix://{self.root}/docker.sock"}
        routes = self.commands.run(["ip", "-j", "route"], prefix=self.prefix).stdout
        if json.loads(routes):
            raise CheckFailed("offline namespace has external routes before deployment")
        self.commands.report.check(
            not self.commands.run(
                ["docker", "image", "ls", "-q"],
                prefix=self.prefix,
                env=self.environment,
            ).stdout.strip(),
            "offline daemon starts with empty image storage",
        )
        for path in self.hidden:
            if path.exists():
                result = self.commands.run(
                    ["test", "-r", str(path)], prefix=self.prefix, check=False
                )
                self.commands.report.check(
                    result.returncode != 0,
                    "producer input hidden from offline recipient",
                )

    def close(self):
        if self.process is not None:
            (self.root / "stop").touch()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                raise CheckFailed(
                    "offline namespace shutdown timed out; retain recovery artifacts"
                )
            finally:
                self.log.close()
            if self.process.returncode:
                raise CheckFailed(
                    "offline supervisor failed; inspect private supervisor.log"
                )


def require_offline(commands):
    missing = [
        name
        for name in ("sudo", "unshare", "nsenter", "mount", "ip", "dockerd", "setpriv")
        if not shutil.which(name)
    ]
    if missing:
        raise Blocked("offline isolation tools missing: " + ", ".join(missing))
    if commands.run(["sudo", "-n", "true"], check=False).returncode:
        raise Blocked(
            "offline isolation requires passwordless sudo for namespaces, a disposable dockerd, and test-owned Containerlab SUID setup"
        )
