"""Reporting, bounded commands, and narrow ownership/comparison contracts."""

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path


class Blocked(RuntimeError):
    pass


class CheckFailed(RuntimeError):
    pass


DIAGNOSTICS = {
    "removed-lean": r"unrecognized arguments: --lean",
    "mode-conflict": r"not allowed with argument|cannot.*(?:offline|runtime)|incompatible",
    "image-conflict": r"requires --offline|external-image.*offline",
    "missing-image": r"(?:image|archive|input).*(?:missing|unavailable|not found|does not exist|could not|cannot)|(?:missing|unavailable).*(?:image|input)",
    "bad-passphrase": r"PKI identity bundle authentication failed",
    "missing-binding": r"unresolved frozen PKI bindings",
    "bad-binding": r"PKI binding .* requires fingerprint .* does not match",
    "incomplete": r"offline.*(?:missing|incomplete)|wheelhouse.*(?:missing|empty)|missing.*(?:runtime|wheelhouse|Containerlab)",
    "tool-mismatch": r"(?:Containerlab|vrnetlab).*(?:differs|mismatch)|runtime archive rejects tool overrides",
}


def expected_failure(kind, returncode, diagnostic):
    return returncode > 0 and bool(
        re.search(DIAGNOSTICS[kind], diagnostic, re.IGNORECASE | re.DOTALL)
    )


def owned_container(labels, lab):
    return labels.get("containerlab") == lab


def merge_catalog(catalog, additions, *, remove=False):
    """Preserve all unrelated entries; a changed test entry is never removed."""
    result = json.loads(json.dumps(catalog))
    for section, entries in additions.items():
        target = result.setdefault(section, {})
        for name, value in entries.items():
            if remove:
                if name in target and target[name] != value:
                    raise CheckFailed("test catalog entry changed; refusing cleanup")
                target.pop(name, None)
            elif name in target:
                raise CheckFailed("test catalog name already exists")
            else:
                target[name] = value
    return result


def normalize(value, paths=(), aliases=None):
    """Only explicit path prefixes and exact identity aliases may differ.

    Do not remove arbitrary keys, hashes, addresses, env values or timestamps.
    Callers explicitly select invariant certificate fields before comparison.
    """
    aliases = aliases or {}
    if isinstance(value, dict):
        return {key: normalize(item, paths, aliases) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item, paths, aliases) for item in value]
    if isinstance(value, str):
        if value in aliases:
            return aliases[value]
        for source, target in sorted(
            paths, key=lambda pair: len(str(pair[0])), reverse=True
        ):
            source = str(source).rstrip("/")
            if value == source or value.startswith(source + "/"):
                return str(target) + value[len(source) :]
    return value


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Report:
    def __init__(self, root, mode, planned):
        self.root = root
        self.secrets = []
        self.current = "setup"
        self.data = {
            "mode": mode,
            "status": "running",
            "planned": planned,
            "commands": [],
            "assertions": [],
            "cases": [],
            "cleanup": [],
        }

    def sanitize(self, value):
        text = str(value)
        text = re.sub(
            r"-----BEGIN [^-]+-----.*?-----END [^-]+-----",
            "<PEM omitted>",
            text,
            flags=re.DOTALL,
        )
        text = re.sub(r"https?://[^\s]+", "<URL omitted>", text)
        text = re.sub(
            r"(?im)^.*(?:\bset\s+password\s+\S+|\b(?:sshpass|password|passphrase|token|credential)\s*[:=]\s*\S+|\bprivate[-_ ]key\s*[:=].*|\bserial[-_ ]number\s*[:=].*|\blicense[-_ ](?:pool|file)\s*[:=]\s*\S+).*$",
            "<sensitive diagnostic omitted>",
            text,
        )
        for secret in sorted(self.secrets, key=len, reverse=True):
            if secret:
                text = text.replace(secret, "<private>")
        return text[-12000:]

    def check(self, condition, message):
        self.data["assertions"].append(
            {"case": self.current, "assertion": message, "passed": bool(condition)}
        )
        if not condition:
            raise CheckFailed(message)

    def write(self):
        path = self.root / "report.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
        lines = [f"Freeze round-trip: {self.data['mode']} — {self.data['status']}"]
        lines.extend(
            f"{c['id']}: {c['status']} ({c.get('seconds', 0):.1f}s) {c.get('reason', '')}"
            for c in self.data["cases"]
        )
        lines.extend(self.data.get("blockers", []))
        (self.root / "summary.txt").write_text("\n".join(lines) + "\n")


class Commands:
    def __init__(self, report, environment):
        self.report = report
        self.environment = environment

    def run(
        self,
        argv,
        *,
        cwd=None,
        env=None,
        timeout=300,
        check=True,
        private=False,
        prefix=(),
    ):
        started = time.monotonic()
        environment = self.environment | (env or {})
        # sudo resets its environment. Reapply only explicit test/runtime values
        # after setpriv has dropped privileges inside the namespace.
        forwarded = []
        if prefix:
            allowed = {
                "PATH",
                "DOCKER_HOST",
                "XDG_STATE_HOME",
                "XDG_CACHE_HOME",
                "PIP_NO_INDEX",
                "PIP_FIND_LINKS",
                "CONTAINERLAB_BIN",
                "CONTAINERLAB_SCHEMA",
                "CONTAINERLAB_UPDATE",
                "VRNETLAB_DIR",
                "VRNETLAB_UPDATE",
            }
            forwarded = [
                "env",
                *(
                    f"{key}={value}"
                    for key, value in environment.items()
                    if key in allowed or key in (env or {})
                ),
            ]
        args = [str(item) for item in (*prefix, *forwarded, *argv)]
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            while True:
                try:
                    output, _ = process.communicate(timeout=min(30, timeout))
                    break
                except subprocess.TimeoutExpired:
                    print(
                        f"[{self.report.current}] running {Path(args[len(prefix)]).name} ({time.monotonic() - started:.0f}s)",
                        flush=True,
                    )
                    if time.monotonic() - started >= timeout:
                        timed_out = True
                        raise
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                output, _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate()
            if not timed_out:
                raise
        record = {
            "case": self.report.current,
            "argv": [self.report.sanitize(a) for a in args],
            "cwd": str(cwd) if cwd else None,
            "seconds": round(time.monotonic() - started, 3),
            "returncode": process.returncode,
            "timeout": timed_out,
            "diagnostic": "<private output omitted>"
            if private
            else self.report.sanitize(output),
        }
        self.report.data["commands"].append(record)
        self.report.write()
        if timed_out:
            raise CheckFailed(f"command timed out after {timeout}s")
        if check and process.returncode:
            raise CheckFailed(
                f"command failed ({process.returncode}): {Path(args[len(prefix)]).name}; see report"
            )
        return subprocess.CompletedProcess(args, process.returncode, output, "")
