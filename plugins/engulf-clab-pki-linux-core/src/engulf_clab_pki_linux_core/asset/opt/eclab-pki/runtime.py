#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

OWNED = Path("/opt/eclab-pki")
STATE = OWNED / "state"
CLIENTS = {"CURL", "WGET", "GIT", "PYTHON", "NODE", "JAVA", "LFTP", "SMBCLIENT", "LDAP"}
SERVERS = {"NGINX", "SLAPD", "SAMBA", "DOT", "DOH"}
PROGRAMS = tuple(sorted(CLIENTS | SERVERS | {"SQUID", "CHROME", "CHROMIUM", "FIREFOX", "PLAYWRIGHT"}))
COMMANDS = {
    "CURL": ("curl",), "WGET": ("wget",), "GIT": ("git",), "PYTHON": ("python3",),
    "NODE": ("node",), "JAVA": ("java",), "LFTP": ("lftp",),
    "SMBCLIENT": ("smbclient",), "LDAP": ("ldapsearch",), "NGINX": ("nginx",),
    "SLAPD": ("slapd",), "SAMBA": ("smbd",), "DOT": ("kdig",),
    "DOH": ("doh-client",), "SQUID": ("squid",), "CHROME": ("google-chrome",),
    "CHROMIUM": ("chromium", "chromium-browser"),
    "FIREFOX": ("firefox", "firefox-esr"), "PLAYWRIGHT": ("playwright",),
}


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def truth(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


def safe_root() -> Path | None:
    value = os.environ.get("ECLAB_PKI_ROOT")
    if not value:
        if truth(os.environ.get("ECLAB_PKI_REQUIRED")):
            fail("ECLAB_PKI_REQUIRED is true but ECLAB_PKI_ROOT is unset")
        return None
    root = Path(value)
    if not root.is_absolute() or ".." in root.parts:
        fail("ECLAB_PKI_ROOT must be an absolute normalized path")
    inventory = root / "inventory.json"
    if root.is_symlink() or not root.is_dir() or inventory.is_symlink() or not inventory.is_file():
        if truth(os.environ.get("ECLAB_PKI_REQUIRED")):
            fail("required PKI mount is unavailable or unsafe")
        return None
    return root.resolve()


def artifact(root: Path, item: dict[str, object], name: str) -> Path:
    relative = item.get("path")
    if not isinstance(relative, str):
        fail("PKI inventory identity has no path")
    candidate = root / relative / name
    current = candidate
    while current != root:
        if current.is_symlink():
            fail(f"PKI artifact path contains a symlink: {candidate}")
        current = current.parent
    try:
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        fail(f"PKI artifact escapes its mount: {candidate}")
    if candidate.is_symlink() or not candidate.is_file():
        fail(f"PKI artifact is unavailable: {candidate}")
    return candidate


def identities(root: Path, document: dict[str, object], section: str) -> list[dict[str, object]]:
    values = document.get(section, [])
    if not isinstance(values, list):
        fail(f"PKI inventory {section} must be an array of objects")
    result: list[dict[str, object]] = []
    for item in values:
        if not isinstance(item, dict):
            fail(f"PKI inventory {section} must be an array of objects")
        identity_id = item.get("identity_id")
        if not isinstance(identity_id, str) or identity_id.count("/") not in {1, 2}:
            fail(f"PKI inventory {section} has an invalid canonical identity ID")
        artifact(root, item, "certificate.pem")
        result.append(item)
    return result


def resolve(reference: str, values: list[dict[str, object]]) -> dict[str, object]:
    exact = [item for item in values if item["identity_id"] == reference]
    if not exact and "/" not in reference:
        exact = [item for item in values if str(item["identity_id"]).split("/")[1] == reference]
    if len(exact) != 1:
        fail(f"PKI identity selector {reference!r} is {'unknown' if not exact else 'ambiguous'}")
    return exact[0]


def extended_key_usage(item: dict[str, object]) -> list[str]:
    value = item.get("extended_key_usage", [])
    if not isinstance(value, list) or any(not isinstance(entry, str) for entry in value):
        fail(f"identity {item.get('identity_id')} has invalid extended_key_usage")
    return value


def subject_issuer(certificate: Path) -> tuple[str, str]:
    output = subprocess.run(
        ["openssl", "x509", "-in", str(certificate), "-noout", "-subject", "-issuer", "-nameopt", "RFC2253"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    if len(output) != 2:
        fail(f"could not read certificate subject and issuer: {certificate}")
    values: list[str] = []
    for line in output:
        distinguished_name = line.partition("=")[2]
        match = re.search(r"(?:^|,)CN=([^,]+)", distinguished_name)
        if match is None:
            fail(f"certificate has no distinguishable common name: {certificate}")
        values.append(match.group(1))
    return values[0], values[1]


def write_environment(values: dict[str, str]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    target = STATE / "environment"
    # The file is meant to be sourced ('. .../environment'), and the adapters it
    # configures are separate processes, so every name has to be exported.
    write_owned(
        target,
        "".join(f"export {key}={shlex.quote(value)}\n" for key, value in sorted(values.items())),
    )


def write_owned(target: Path, contents: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.new")
    temporary.write_text(contents)
    temporary.replace(target)


def remove_owned(target: Path) -> None:
    if target.is_symlink():
        fail(f"integration-owned path is an unsafe symlink: {target}")
    if target.exists():
        if not target.is_file():
            fail(f"integration-owned path is not a regular file: {target}")
        target.unlink()


def config_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def configure_curl(env: dict[str, str]) -> None:
    directory = STATE / "curl"
    target = directory / ".curlrc"
    write_owned(
        target,
        "".join(
            (
                f"cert = {config_quote(env['ECLAB_PKI_CURL_FULL_CHAIN_FILE'])}\n",
                f"key = {config_quote(env['ECLAB_PKI_CURL_KEY_FILE'])}\n",
            )
        ),
    )
    env["CURL_HOME"] = str(directory)


def configure_nginx(env: dict[str, str]) -> None:
    target = STATE / "nginx" / "identity.conf"
    write_owned(
        target,
        "".join(
            (
                "# Generated by eclab-pki; include inside an nginx server block.\n",
                f"ssl_certificate {config_quote(env['ECLAB_PKI_NGINX_FULL_CHAIN_FILE'])};\n",
                f"ssl_certificate_key {config_quote(env['ECLAB_PKI_NGINX_KEY_FILE'])};\n",
                f"ssl_trusted_certificate {config_quote(env['ECLAB_PKI_NGINX_CHAIN_FILE'])};\n",
            )
        ),
    )
    env["ECLAB_PKI_NGINX_FRAGMENT"] = str(target)


def install_trust(root: Path, env: dict[str, str]) -> None:
    mode = os.environ.get("ECLAB_PKI_SYSTEM_TRUST", "augment")
    if mode not in {"augment", "isolated"}:
        fail("ECLAB_PKI_SYSTEM_TRUST must be augment or isolated")
    bundle = root / "trust" / "ca-bundle.pem"
    if bundle.is_symlink() or not bundle.is_file():
        fail("PKI trust bundle is unavailable")
    if mode == "augment":
        if Path("/usr/local/share/ca-certificates").is_dir():
            target = Path("/usr/local/share/ca-certificates/eclab-pki.crt")
            shutil.copyfile(bundle, target)
            subprocess.run(["update-ca-certificates"], check=True)
        elif Path("/etc/pki/ca-trust/source/anchors").is_dir():
            target = Path("/etc/pki/ca-trust/source/anchors/eclab-pki.pem")
            shutil.copyfile(bundle, target)
            subprocess.run(["update-ca-trust", "extract"], check=True)
    else:
        env.update({
            "SSL_CERT_FILE": str(bundle), "CURL_CA_BUNDLE": str(bundle),
            "GIT_SSL_CAINFO": str(bundle), "REQUESTS_CA_BUNDLE": str(bundle),
            "NODE_EXTRA_CA_CERTS": str(bundle),
        })
    env["ECLAB_PKI_CA_BUNDLE"] = str(bundle)


def selected_paths(root: Path, item: dict[str, object], env: dict[str, str], prefix: str = "ECLAB_PKI") -> None:
    env[f"{prefix}_CERT_FILE"] = str(artifact(root, item, "certificate.pem"))
    env[f"{prefix}_KEY_FILE"] = str(artifact(root, item, "private-key.pem"))
    env[f"{prefix}_CHAIN_FILE"] = str(artifact(root, item, "chain.pem"))
    env[f"{prefix}_FULL_CHAIN_FILE"] = str(artifact(root, item, "full-chain.pem"))


def configure_selectors(root: Path, leaves: list[dict[str, object]], private: list[dict[str, object]], capabilities: dict[str, bool], env: dict[str, str]) -> None:
    remove_owned(STATE / "curl" / ".curlrc")
    remove_owned(STATE / "nginx" / "identity.conf")
    default = os.environ.get("ECLAB_PKI_IDENTITY_DEFAULT")
    if default:
        item = resolve(default, leaves)
        selected_paths(root, item, env)
    for program in PROGRAMS:
        if not capabilities.get(program, False):
            continue
        reference = os.environ.get(f"ECLAB_PKI_IDENTITY_{program}")
        if not reference:
            reference = default
        if not reference or program in {"CHROME", "CHROMIUM", "FIREFOX", "PLAYWRIGHT"}:
            continue
        catalog = private if program == "SQUID" else leaves
        item = resolve(reference, catalog)
        eku = extended_key_usage(item)
        required = "client_auth" if program in CLIENTS else "server_auth"
        if program != "SQUID" and (not isinstance(eku, list) or required not in eku):
            fail(f"identity {item['identity_id']} is unsuitable for {program}: requires {required}")
        selected_paths(root, item, env, f"ECLAB_PKI_{program}")
        if program == "CURL":
            configure_curl(env)
        elif program == "NGINX":
            configure_nginx(env)


def nss_database(database: Path) -> bool:
    if not shutil.which("certutil"):
        return False
    database.mkdir(parents=True, exist_ok=True)
    if not (database / "cert9.db").exists():
        subprocess.run(["certutil", "-N", "-d", f"sql:{database}", "--empty-password"], check=True)
    return True


def nss_certificates(bundle: Path) -> dict[str, str]:
    contents = bundle.read_text()
    certificates: dict[str, str] = {}
    end = 0
    for match in re.finditer(
        r"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----",
        contents, re.DOTALL,
    ):
        if contents[end:match.start()].strip():
            fail(f"invalid PEM certificate bundle: {bundle}")
        try:
            der = base64.b64decode("".join(match.group(1).split()), validate=True)
        except ValueError:
            fail(f"invalid PEM certificate bundle: {bundle}")
        nickname = "eclab-pki-ca-" + hashlib.sha256(der).hexdigest()
        certificates[nickname] = match.group(0) + "\n"
        end = match.end()
    if contents[end:].strip():
        fail(f"invalid PEM certificate bundle: {bundle}")
    return certificates


def nss_trust(root: Path, database: Path) -> None:
    if not shutil.which("certutil"):
        return
    selected = nss_certificates(artifact(root, {"path": "trust"}, "ca-bundle.pem"))
    owned = database / "eclab-pki-ca-bundle.pem"
    if owned.is_symlink():
        fail(f"integration-owned path is an unsafe symlink: {owned}")
    previous = nss_certificates(owned) if owned.exists() else {}
    nss_database(database)
    # Journal both sets before changing NSS so a failed import can be reconciled
    # on the next startup, even if the node's trust selection changes meanwhile.
    write_owned(owned, "".join((previous | selected).values()))
    for nickname, certificate in (previous | selected).items():
        # -A also updates existing certificates under their PKCS#12 nicknames.
        # Clear only trust previously granted here; never trust incidental chains.
        subprocess.run(
            ["certutil", "-A", "-d", f"sql:{database}", "-n", nickname,
             "-t", "CT,c,c" if nickname in selected else ",,", "-a"],
            input=certificate, text=True, check=True,
        )
    write_owned(owned, "".join(selected.values()))


def nss_databases() -> list[Path]:
    # Chromium reads ~/.pki/nssdb when it exists and falls back to the XDG data
    # directory otherwise, so trust has to reach every database it may consult.
    home = Path.home()
    value = os.environ.get("XDG_DATA_HOME", "")
    data = Path(value) if value.startswith("/") else home / ".local" / "share"
    databases: list[Path] = []
    seen: set[tuple[int, int]] = set()
    for candidate in (home / ".pki" / "nssdb", data / "pki" / "nssdb"):
        try:
            status = candidate.stat()
        except OSError:
            # Nothing to alias yet; startup creates this database below.
            databases.append(candidate)
            continue
        # Device and inode identify one directory reached through a link, a bind
        # mount, or any other aliasing an image may have set up, so a shared
        # database is imported and journalled once instead of twice.
        identity = (status.st_dev, status.st_ino)
        if identity not in seen:
            seen.add(identity)
            databases.append(candidate)
    return databases


def nss_import(root: Path, leaves: list[dict[str, object]], database: Path) -> None:
    if not shutil.which("pk12util") or not nss_database(database):
        return
    for item in leaves:
        eku = item.get("extended_key_usage", [])
        if not isinstance(eku, list) or "client_auth" not in eku:
            continue
        identity_id = str(item["identity_id"])
        bundle = STATE / "browser-bundles" / (identity_id.replace("/", "_") + ".p12")
        bundle.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "openssl", "pkcs12", "-export", "-passout", "pass:",
            "-inkey", str(artifact(root, item, "private-key.pem")),
            "-in", str(artifact(root, item, "certificate.pem")),
            "-certfile", str(artifact(root, item, "chain.pem")), "-out", str(bundle),
            "-name", identity_id,
        ], check=True)
        subprocess.run(
            ["certutil", "-D", "-d", f"sql:{database}", "-n", identity_id],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(["pk12util", "-i", str(bundle), "-d", f"sql:{database}", "-W", ""], check=True)


def firefox_profile(root: Path, leaves: list[dict[str, object]], reference: str) -> Path:
    item = resolve(reference, [value for value in leaves if "client_auth" in extended_key_usage(value)])
    profile = STATE / "firefox" / str(item["identity_id"]).replace("/", "_")
    if profile.exists():
        shutil.rmtree(profile)
    nss_import(root, [item], profile)
    nss_trust(root, profile)
    return profile


def browser_rules(root: Path, leaves: list[dict[str, object]], env: dict[str, str]) -> None:
    raw = os.environ.get("ECLAB_PKI_BROWSER_CLIENT_CERTS", "[]")
    try:
        rules = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"ECLAB_PKI_BROWSER_CLIENT_CERTS is invalid JSON: {error}")
    if not isinstance(rules, list):
        fail("ECLAB_PKI_BROWSER_CLIENT_CERTS must be a JSON array of objects")
    policies: dict[str, list[dict[str, object]]] = {"chrome": [], "chromium": []}
    playwright: list[dict[str, str]] = []
    client_leaves = [item for item in leaves if "client_auth" in extended_key_usage(item)]
    for rule in rules:
        if not isinstance(rule, dict):
            fail("ECLAB_PKI_BROWSER_CLIENT_CERTS must be a JSON array of objects")
        browser, origin, reference = rule.get("browser"), rule.get("origin"), rule.get("identity")
        if (
            not isinstance(browser, str)
            or browser not in {"chrome", "chromium", "firefox", "playwright", "webkit"}
            or not isinstance(origin, str)
            or not isinstance(reference, str)
        ):
            fail("browser client-certificate rule has invalid browser, origin, or identity")
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            fail(f"browser client-certificate origin must be an exact HTTPS origin: {origin!r}")
        item = resolve(reference, client_leaves)
        certificate = artifact(root, item, "certificate.pem")
        key = artifact(root, item, "private-key.pem")
        subject, issuer = subject_issuer(certificate)
        if browser in {"chrome", "chromium"}:
            indistinguishable = [other for other in client_leaves if subject_issuer(artifact(root, other, "certificate.pem")) == (subject, issuer)]
            if len(indistinguishable) != 1:
                fail(f"Chrome subject/issuer filter cannot distinguish identity {item['identity_id']}")
            policies[browser].append({"pattern": origin, "filter": {"SUBJECT": {"CN": subject}, "ISSUER": {"CN": issuer}}})
        playwright.append({"origin": origin, "certPath": str(certificate), "keyPath": str(key)})
    for browser, browser_policies in policies.items():
        if not browser_policies:
            continue
        policy_root = Path(
            "/etc/opt/chrome/policies/managed"
            if browser == "chrome"
            else "/etc/chromium/policies/managed"
        )
        policy_root.mkdir(parents=True, exist_ok=True)
        (policy_root / "eclab-pki.json").write_text(
            json.dumps(
                {
                    "AutoSelectCertificateForUrls": [
                        json.dumps(value) for value in browser_policies
                    ]
                },
                indent=2,
            )
            + "\n"
        )
    descriptor = STATE / "playwright-client-certificates.json"
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(json.dumps(playwright, indent=2) + "\n")
    env["ECLAB_PKI_PLAYWRIGHT_CLIENT_CERTIFICATES"] = str(descriptor)


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    root = safe_root()
    if root is None:
        write_environment({})
        return
    try:
        document = json.loads((root / "inventory.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read PKI inventory: {error}")
    if not isinstance(document, dict) or document.get("version") != 2:
        fail("Linux PKI integration requires inventory version 2")
    if any(key in document for key in ("crls", "ocsp", "certificate_databases")):
        fail("managed revocation and certificate-database activation is not implemented")
    leaves = identities(root, document, "issued_identities")
    private = identities(root, document, "requested_private_authorities")
    capabilities = {
        program: any(shutil.which(command) is not None for command in commands)
        for program, commands in COMMANDS.items()
    }
    (STATE / "capabilities.json").write_text(json.dumps(capabilities, indent=2, sort_keys=True) + "\n")
    env: dict[str, str] = {}
    install_trust(root, env)
    configure_selectors(root, leaves, private, capabilities, env)
    if capabilities["CHROME"] or capabilities["CHROMIUM"]:
        for database in nss_databases():
            nss_import(root, leaves, database)
            nss_trust(root, database)
    if capabilities["FIREFOX"]:
        database = STATE / "firefox" / "all"
        nss_import(root, leaves, database)
        nss_trust(root, database)
    browser_rules(root, leaves, env)
    write_environment(env)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--firefox-profile":
            selected_root = safe_root()
            if selected_root is None:
                fail("Firefox identity profile requires a PKI mount")
            selected_document = json.loads((selected_root / "inventory.json").read_text())
            selected_leaves = identities(selected_root, selected_document, "issued_identities")
            print(firefox_profile(selected_root, selected_leaves, sys.argv[2]))
        else:
            main()
    except Exception as error:  # noqa: BLE001 - entrypoint converts diagnostics to exit status
        print(f"eclab-pki: {error}", file=sys.stderr)
        raise SystemExit(1)
