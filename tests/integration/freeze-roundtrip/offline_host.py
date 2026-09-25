"""Root supervisor. Copied into the work directory before hiding the checkout.

Only dockerd and namespace setup run elevated. Every eclab call is made by the
parent through setpriv with the original non-root identity.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def run(*args):
    subprocess.run(args, check=True, stdin=subprocess.DEVNULL)


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    root = Path(config["root"])
    if os.geteuid() != 0 or config["uid"] == 0:
        raise RuntimeError(
            "namespace supervisor requires root and an unprivileged recipient"
        )
    run("mount", "--make-rprivate", "/")
    run("ip", "link", "set", "lo", "up")
    for item in config["hidden"]:
        path = Path(item)
        if path.is_dir():
            run(
                "mount",
                "-t",
                "tmpfs",
                "-o",
                "mode=000,size=4k",
                "freeze-hidden",
                str(path),
            )
        else:
            empty = root / "hidden-file"
            empty.touch(mode=0o000, exist_ok=True)
            run("mount", "--bind", str(empty), str(path))
    log = (root / "dockerd.log").open("w")
    os.chmod(root / "dockerd.log", 0o600)
    daemon = subprocess.Popen(
        [
            "dockerd",
            "--host",
            f"unix://{root}/docker.sock",
            "--data-root",
            str(root / "data"),
            "--exec-root",
            str(root / "exec"),
            "--pidfile",
            str(root / "dockerd.pid"),
            "--bridge=none",
            "--iptables=false",
            "--ip-forward=false",
            "--ip-masq=false",
        ],
        stdout=log,
        stderr=log,
    )
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        deadline = time.monotonic() + 35
        while not (root / "docker.sock").exists():
            if daemon.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("disposable Docker daemon failed startup")
            time.sleep(0.2)
        os.chown(root / "docker.sock", 0, config["gid"])
        os.chmod(root / "docker.sock", 0o660)
        ready = root / "ready.json"
        ready.write_text(json.dumps({"pid": os.getpid()}))
        os.chown(ready, config["uid"], config["gid"])
        while not stopping and not (root / "stop").exists():
            if daemon.poll() is not None:
                raise RuntimeError("disposable Docker daemon exited")
            time.sleep(0.2)
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=20)
        except subprocess.TimeoutExpired:
            daemon.kill()
            daemon.wait()
        log.close()


if __name__ == "__main__":
    main()
