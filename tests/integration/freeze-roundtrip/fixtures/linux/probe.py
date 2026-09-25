"""Guest probe: emit public observations only, never private PEM or credentials."""

import hashlib
import json
import os
import socket
import ssl
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes


def certificate(path):
    cert = x509.load_pem_x509_certificate(path.read_bytes())

    def extension(cls):
        try:
            return cert.extensions.get_extension_for_class(cls).value
        except x509.ExtensionNotFound:
            return None

    sans = extension(x509.SubjectAlternativeName)
    eku = extension(x509.ExtendedKeyUsage)
    usage = extension(x509.KeyUsage)
    constraints = extension(x509.BasicConstraints)
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "sans": sorted(str(value.value) for value in sans) if sans else [],
        "eku": sorted(oid.dotted_string for oid in eku) if eku else [],
        "key_usage": [
            getattr(usage, key)
            for key in (
                "digital_signature",
                "key_encipherment",
                "key_cert_sign",
                "crl_sign",
            )
        ]
        if usage
        else [],
        "ca": constraints.ca if constraints else False,
        "fingerprint": cert.fingerprint(hashes.SHA256()).hex(),
    }


def projection(root):
    inventory = json.loads((root / "inventory.json").read_text())
    selected = {}
    for section in (
        "trusted_authorities",
        "requested_private_authorities",
        "issued_identities",
    ):
        selected[section] = []
        for entry in inventory[section]:
            directory = root / entry["path"]
            selected[section].append(
                {
                    "id": entry["identity_id"],
                    "certificate": certificate(directory / "certificate.pem"),
                }
            )
    # Public-key.pem is part of the public certificate view and does not expose
    # signing material. Check only the canonical private-key filename.
    keys = sorted(str(p.relative_to(root)) for p in root.rglob("private-key.pem"))
    permissions = {
        str(p.relative_to(root)): oct(p.stat().st_mode & 0o777)
        for p in root.rglob("private-key.pem")
    }
    chains = {}
    for entry in inventory["issued_identities"]:
        chain = root / entry["path"] / "full-chain.pem"
        check = subprocess.run(
            [
                "openssl",
                "verify",
                "-CAfile",
                str(root / "trust/ca-bundle.pem"),
                "-untrusted",
                str(chain),
                str(chain.parent / "certificate.pem"),
            ],
            capture_output=True,
            check=False,
        )
        chains[entry["identity_id"]] = check.returncode == 0
    return {
        "selected": selected,
        "private_keys": keys,
        "permissions": permissions,
        "chains": chains,
    }


if __name__ == "__main__":
    root = Path("/mnt/eclab/pki")
    result = projection(root)
    result["markers"] = [
        Path("/roundtrip-base").read_text().strip(),
        Path("/roundtrip-linux").read_text().strip(),
    ]
    result["value"] = os.environ["ROUNDTRIP_VALUE"]
    context = ssl.create_default_context(cafile=str(root / "trust/ca-bundle.pem"))
    with (
        socket.create_connection(("198.18.77.1", 443), timeout=10) as tcp,
        context.wrap_socket(tcp, server_hostname="freeze-roundtrip.test") as tls,
    ):
        peer_certificate = tls.getpeercert(binary_form=True)
        if peer_certificate is None:
            raise RuntimeError("HTTPS peer did not provide a certificate")
        result["https_fingerprint"] = hashlib.sha256(peer_certificate).hexdigest()
    negative = ssl.create_default_context(
        cafile=str(root / "authorities/local/untrusted/default/certificate.pem")
    )
    try:
        with (
            socket.create_connection(("198.18.77.1", 443), timeout=10) as tcp,
            negative.wrap_socket(tcp, server_hostname="freeze-roundtrip.test"),
        ):
            result["untrusted_rejected"] = False
    except ssl.SSLCertVerificationError:
        result["untrusted_rejected"] = True
    print(json.dumps(result, sort_keys=True))
