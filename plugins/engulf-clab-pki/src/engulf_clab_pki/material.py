from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed448, ed25519, mldsa, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ObjectIdentifier

from .catalog import EffectiveCatalog, Scope


class MaterialError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorityMaterial:
    scope: Scope
    name: str
    variant: str
    directory: Path
    certificate: x509.Certificate
    private_key: Any
    chain: tuple[x509.Certificate, ...]
    generation: str

    @property
    def fingerprint(self) -> str:
        return self.certificate.fingerprint(hashes.SHA256()).hex()


@dataclass(frozen=True, slots=True)
class LeafMaterial:
    node: str
    name: str
    directory: Path
    certificate: x509.Certificate
    private_key: Any
    chain: tuple[x509.Certificate, ...]

    @property
    def fingerprint(self) -> str:
        return self.certificate.fingerprint(hashes.SHA256()).hex()


@dataclass(slots=True)
class MaterialSet:
    authorities: dict[tuple[Scope, str, str], AuthorityMaterial]
    leaves: dict[tuple[str, str], LeafMaterial]
    created: list[Path]


def generate_catalog(
    catalog: EffectiveCatalog,
    *,
    user_root: Path,
    workspace_root: Path,
) -> MaterialSet:
    result = MaterialSet({}, {}, [])

    def authority(scope: Scope, name: str, variant: str) -> AuthorityMaterial:
        key = (scope, name, variant)
        if key in result.authorities:
            return result.authorities[key]
        source = catalog.global_catalog if scope == "global" else catalog.local_catalog
        spec = source.get("authorities", {}).get(name)
        if not isinstance(spec, dict):
            raise MaterialError(f"missing authority {scope}/{name}")
        variant_spec = spec.get("variants", {}).get(variant, {}) if variant != "default" else {}
        issuer_ref = variant_spec.get("issuer", spec.get("issuer"))
        issuer: AuthorityMaterial | None = None
        if issuer_ref is not None:
            issuer_scope, issuer_name, issuer_variant, _ = catalog.resolve_authority(
                str(issuer_ref), owner=scope
            )
            issuer = authority(issuer_scope, issuer_name, issuer_variant)
        root = _authority_root(catalog, scope, spec, user_root, workspace_root)
        identity_spec = _identity_spec(spec)
        restored = _restored_authority(catalog, scope, spec, root, name, variant)
        if restored is not None:
            private_key, cert, chain, directory = restored
            material = AuthorityMaterial(
                scope, name, variant, directory, cert, private_key, chain, directory.name
            )
            result.authorities[key] = material
            return material
        identity_hash = _digest({"identity": identity_spec})
        identity_dir = root / name / "identities" / identity_hash
        private_path = identity_dir / "private-key.pem"
        if private_path.is_file():
            private_key = serialization.load_pem_private_key(private_path.read_bytes(), None)
        else:
            private_key = _private_key(
                _merged(catalog.defaults.get("authority", {}), identity_spec)
            )
        signing_spec = _merged(spec, variant_spec)
        issuer_fingerprint = issuer.fingerprint if issuer else "self"
        generation = _digest(
            {"definition": signing_spec, "issuer": issuer_fingerprint, "identity": identity_hash}
        )
        directory = root / name / "generations" / variant / generation
        cert_path = directory / "certificate.pem"
        if cert_path.is_file() and private_path.is_file():
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            chain = (cert, *_load_chain(directory / "chain.pem"))
        else:
            if not identity_dir.exists():
                _atomic_directory(
                    identity_dir,
                    {
                        "private-key.pem": _private_bytes(private_key),
                        "public-key.pem": _public_bytes(private_key),
                    },
                )
                result.created.append(identity_dir)
            profile = _profile(
                catalog, signing_spec, scope, ca=True, intermediate=issuer is not None
            )
            cert = _certificate(
                private_key,
                issuer.private_key if issuer else private_key,
                issuer.certificate if issuer else None,
                profile,
                default_cn=name,
                ca=True,
            )
            chain = (cert, *(issuer.chain if issuer else ()))
            files = _artifact_files(private_key, cert, chain, signing_spec, include_private=False)
            _atomic_directory(directory, files)
            result.created.append(directory)
        material = AuthorityMaterial(
            scope, name, variant, directory, cert, private_key, chain, generation
        )
        result.authorities[key] = material
        return material

    for scope_value, source in (
        ("global", catalog.global_catalog),
        ("local", catalog.local_catalog),
    ):
        scope = cast(Scope, scope_value)
        for name, spec in source.get("authorities", {}).items():
            authority(scope, name, "default")
            for variant in spec.get("variants", {}):
                authority(scope, name, variant)

    for node, node_spec in catalog.nodes.items():
        for request in node_spec.get("certificates", []):
            request_name = request["name"]
            request_scope = cast(Scope, request.get("scope", "local"))
            issuer_scope, issuer_name, issuer_variant, _ = catalog.resolve_authority(
                request["issuer"], owner=request_scope
            )
            issuer = authority(issuer_scope, issuer_name, issuer_variant)
            profile = _profile(catalog, request, request_scope, ca=False, intermediate=False)
            profile = _merged(profile, request)
            profile.setdefault("subject", {})
            profile["subject"].setdefault("common_name", node)
            profile.setdefault("sans", {})
            profile.pop("node_dns_san", None)
            restored_leaf = _restored_leaf(request, node, request_name)
            if restored_leaf is not None:
                private_key, cert, chain, directory = restored_leaf
                result.leaves[(node, request_name)] = LeafMaterial(
                    node, request_name, directory, cert, private_key, chain
                )
                continue
            definition_hash = _digest(
                {"request": profile, "issuer": issuer.fingerprint, "node": node}
            )
            directory = workspace_root / "pki" / "issued" / node / request_name / definition_hash
            cert_path = directory / "certificate.pem"
            key_path = directory / "private-key.pem"
            if cert_path.is_file() and key_path.is_file():
                private_key = serialization.load_pem_private_key(key_path.read_bytes(), None)
                cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
                chain = (cert, *_load_chain(directory / "chain.pem"))
            else:
                private_key = _private_key(profile)
                cert = _certificate(
                    private_key,
                    issuer.private_key,
                    issuer.certificate,
                    profile,
                    default_cn=node,
                    ca=False,
                )
                chain = (cert, *issuer.chain)
                _atomic_directory(
                    directory,
                    _artifact_files(private_key, cert, chain, profile, include_private=True),
                )
                result.created.append(directory)
            result.leaves[(node, request_name)] = LeafMaterial(
                node, request_name, directory, cert, private_key, chain
            )
    return result


def _authority_root(
    catalog: EffectiveCatalog,
    scope: Scope,
    spec: dict[str, Any],
    user_root: Path,
    workspace_root: Path,
) -> Path:
    store = spec.get("store")
    if isinstance(store, str):
        store_scope, _name, store_spec = catalog.resolve("stores", store, owner=scope)
        if store_spec.get("type", "generated") == "directory":
            path = store_spec.get("path")
            if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
                raise MaterialError("explicit directory stores require an absolute path")
            return Path(path).expanduser().resolve()
        scope = store_scope
    if scope == "local" and spec.get("lifetime") == "ephemeral":
        return workspace_root / "pki" / "ephemeral" / "authorities"
    return (user_root if scope == "global" else workspace_root) / "pki" / "authorities"


def _identity_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in spec.items()
        if key not in {"issuer", "variants", "store", "lifetime", "freeze"}
    }


def _restored_authority(
    catalog: EffectiveCatalog,
    scope: Scope,
    spec: dict[str, Any],
    root: Path,
    name: str,
    variant: str,
) -> tuple[Any, x509.Certificate, tuple[x509.Certificate, ...], Path] | None:
    store = spec.get("store")
    if not isinstance(store, str):
        return None
    _store_scope, _store_name, store_spec = catalog.resolve("stores", store, owner=scope)
    snapshots = store_spec.get("snapshot_definitions")
    if not isinstance(snapshots, dict):
        return None
    expected = hashlib.sha256(
        json.dumps(_identity_spec(spec), sort_keys=True, default=str).encode()
    ).hexdigest()
    if snapshots.get(name) != expected:
        return None
    identities = sorted(
        (root / name / "identities").glob("*/private-key.pem"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    generations = sorted(
        (root / name / "generations" / variant).glob("*/certificate.pem"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not identities or not generations:
        raise MaterialError(f"restored snapshot for {scope}/{name}/{variant} is incomplete")
    private_key = serialization.load_pem_private_key(identities[0].read_bytes(), None)
    certificate_path = generations[0]
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    expected_public = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    actual_public = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if actual_public != expected_public:
        raise MaterialError(f"restored snapshot for {scope}/{name}/{variant} has a key mismatch")
    directory = certificate_path.parent
    return private_key, certificate, (certificate, *_load_chain(directory / "chain.pem")), directory


def _restored_leaf(
    request: dict[str, Any], node: str, name: str
) -> tuple[Any, x509.Certificate, tuple[x509.Certificate, ...], Path] | None:
    snapshots = request.get("restored_snapshots")
    snapshot = snapshots.get(node) if isinstance(snapshots, dict) else request.get("restored_snapshot")
    if not isinstance(snapshot, dict):
        return None
    expected = hashlib.sha256(
        json.dumps(
            {
                key: value
                for key, value in request.items()
                if key
                not in {
                    "freeze",
                    "restored_snapshot",
                    "restored_snapshots",
                    "name",
                    "scope",
                    "declaration_name",
                }
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    if snapshot.get("definition_sha256") != expected:
        return None
    path_value = snapshot.get("path")
    if not isinstance(path_value, str):
        raise MaterialError(f"restored snapshot for leaf {node}/{name} has no path")
    directory = Path(path_value).expanduser().resolve()
    private_path = directory / "private-key.pem"
    certificate_path = directory / "certificate.pem"
    if not private_path.is_file() or not certificate_path.is_file():
        raise MaterialError(f"restored snapshot for leaf {node}/{name} is incomplete")
    private_key = serialization.load_pem_private_key(private_path.read_bytes(), None)
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    expected_public = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    actual_public = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if actual_public != expected_public:
        raise MaterialError(f"restored snapshot for leaf {node}/{name} has a key mismatch")
    return private_key, certificate, (certificate, *_load_chain(directory / "chain.pem")), directory


def _profile(
    catalog: EffectiveCatalog,
    spec: dict[str, Any],
    owner: Scope,
    *,
    ca: bool,
    intermediate: bool,
) -> dict[str, Any]:
    defaults = catalog.defaults.get("authority" if ca else "leaf", {})
    result = _merged(_builtin_profile(ca=ca, intermediate=intermediate), defaults)
    profile_name = spec.get("profile")
    if profile_name is not None:
        if not isinstance(profile_name, str):
            raise MaterialError("profile reference must be a string")
        if profile_name == "tls-peer" and not ca:
            declared = _builtin_profile(ca=False, intermediate=False)
        else:
            _scope, _name, declared = catalog.resolve("profiles", profile_name, owner=owner)
        result = _merged(result, declared)
    result = _merged(
        result,
        {
            key: value
            for key, value in spec.items()
            if key
            not in {
                "variants",
                "issuer",
                "freeze",
                "restored_snapshot",
                "name",
                "scope",
                "declaration_name",
            }
        },
    )
    algorithm = result.get("algorithm", "rsa")
    algorithm_name = algorithm if isinstance(algorithm, str) else algorithm.get("name", "rsa")
    if (
        not ca
        and str(algorithm_name).lower() in {"ecdsa", "ec", "ed25519", "ed448", "ml-dsa", "mldsa"}
        and result.get("key_usage") == ["digital_signature", "key_encipherment"]
    ):
        result["key_usage"] = ["digital_signature"]
    return result


def _builtin_profile(*, ca: bool, intermediate: bool) -> dict[str, Any]:
    if ca:
        return {
            "algorithm": {"name": "rsa", "bits": 3072},
            "validity_days": 3650 if intermediate else 7300,
            "basic_constraints": {"ca": True, "path_length": None},
            "key_usage": ["digital_signature", "key_cert_sign", "crl_sign"],
        }
    return {
        "algorithm": {"name": "rsa", "bits": 2048},
        "validity_days": 397,
        "key_usage": ["digital_signature", "key_encipherment"],
        "extended_key_usage": ["server_auth", "client_auth"],
    }


def _merged(base: Any, override: Any) -> dict[str, Any]:
    result = dict(base) if isinstance(base, dict) else {}
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merged(result[key], value)
        else:
            result[key] = value
    return result


def _private_key(spec: dict[str, Any]) -> Any:
    value = spec.get("algorithm", "rsa")
    if isinstance(value, str):
        name, options = value.lower(), {}
    elif isinstance(value, dict):
        name, options = str(value.get("name", "rsa")).lower(), value
    else:
        raise MaterialError("algorithm must be a string or mapping")
    if name == "rsa":
        bits = int(options.get("bits", 3072))
        if bits < 2048:
            raise MaterialError("RSA keys must be at least 2048 bits")
        return rsa.generate_private_key(public_exponent=65537, key_size=bits)
    if name in {"ecdsa", "ec"}:
        curve_name = str(options.get("curve", "secp256r1")).lower()
        if curve_name == "secp256r1":
            return ec.generate_private_key(ec.SECP256R1())
        if curve_name == "secp384r1":
            return ec.generate_private_key(ec.SECP384R1())
        if curve_name == "secp521r1":
            return ec.generate_private_key(ec.SECP521R1())
        raise MaterialError(f"unsupported ECDSA curve: {curve_name}")
    if name == "ed25519":
        return ed25519.Ed25519PrivateKey.generate()
    if name == "ed448":
        return ed448.Ed448PrivateKey.generate()
    if name in {"ml-dsa", "mldsa"}:
        parameter_set = str(options.get("parameter_set", "65"))
        if parameter_set not in {"44", "65", "87"}:
            raise MaterialError("ML-DSA parameter_set must be 44, 65, or 87")
        try:
            if parameter_set == "44":
                return mldsa.MLDSA44PrivateKey.generate()
            if parameter_set == "65":
                return mldsa.MLDSA65PrivateKey.generate()
            if parameter_set == "87":
                return mldsa.MLDSA87PrivateKey.generate()
            raise AssertionError("validated ML-DSA parameter set was not dispatched")
        except Exception as error:
            raise MaterialError(
                "ML-DSA is unavailable from the installed cryptographic provider"
            ) from error
    raise MaterialError(f"unsupported key algorithm: {name}")


def _certificate(
    subject_key: Any,
    issuer_key: Any,
    issuer_certificate: x509.Certificate | None,
    spec: dict[str, Any],
    *,
    default_cn: str,
    ca: bool,
) -> x509.Certificate:
    now = datetime.now(UTC)
    subject = _subject(spec.get("subject", {}), default_cn)
    issuer_name = issuer_certificate.subject if issuer_certificate else subject
    serial_value = spec.get("serial")
    serial = (
        x509.random_serial_number()
        if serial_value is None or serial_value == "random"
        else int(serial_value)
    )
    if serial <= 0 or serial.bit_length() > 159:
        raise MaterialError("certificate serial must be positive and at most 159 bits")
    not_before = _certificate_time(spec.get("not_before"), now - timedelta(days=2))
    not_after = _certificate_time(
        spec.get("not_after"),
        now + timedelta(days=int(spec.get("validity_days", 365))),
    )
    if not_after <= not_before:
        raise MaterialError("certificate not_after must be later than not_before")
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(subject_key.public_key())
        .serial_number(serial)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
    )
    constraints = spec.get("basic_constraints", {"ca": ca})
    if not isinstance(constraints, dict):
        raise MaterialError("basic_constraints must be a mapping")
    builder = builder.add_extension(
        x509.BasicConstraints(
            ca=bool(constraints.get("ca", ca)), path_length=constraints.get("path_length")
        ),
        critical=True,
    )
    builder = builder.add_extension(
        x509.SubjectKeyIdentifier.from_public_key(subject_key.public_key()), critical=False
    )
    authority_public = (
        issuer_certificate.public_key() if issuer_certificate else subject_key.public_key()
    )
    builder = builder.add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(cast(Any, authority_public)),
        critical=False,
    )
    usage = set(spec.get("key_usage", []))
    if usage:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature="digital_signature" in usage,
                content_commitment="content_commitment" in usage,
                key_encipherment="key_encipherment" in usage,
                data_encipherment="data_encipherment" in usage,
                key_agreement="key_agreement" in usage,
                key_cert_sign="key_cert_sign" in usage,
                crl_sign="crl_sign" in usage,
                encipher_only="encipher_only" in usage if "key_agreement" in usage else False,
                decipher_only="decipher_only" in usage if "key_agreement" in usage else False,
            ),
            critical=True,
        )
    eku = spec.get("extended_key_usage", [])
    if eku:
        names = {
            "server_auth": ExtendedKeyUsageOID.SERVER_AUTH,
            "client_auth": ExtendedKeyUsageOID.CLIENT_AUTH,
            "code_signing": ExtendedKeyUsageOID.CODE_SIGNING,
            "email_protection": ExtendedKeyUsageOID.EMAIL_PROTECTION,
            "ocsp_signing": ExtendedKeyUsageOID.OCSP_SIGNING,
        }
        builder = builder.add_extension(
            x509.ExtendedKeyUsage(
                [
                    names[str(item)] if str(item) in names else ObjectIdentifier(str(item))
                    for item in eku
                ]
            ),
            critical=False,
        )
    sans = spec.get("sans", {})
    if sans:
        if not isinstance(sans, dict):
            raise MaterialError("sans must be a mapping")
        values: list[x509.GeneralName] = []
        values.extend(x509.DNSName(str(value)) for value in sans.get("dns", []))
        values.extend(x509.IPAddress(ipaddress.ip_address(value)) for value in sans.get("ip", []))
        values.extend(x509.RFC822Name(str(value)) for value in sans.get("email", []))
        values.extend(x509.UniformResourceIdentifier(str(value)) for value in sans.get("uri", []))
        builder = builder.add_extension(x509.SubjectAlternativeName(values), critical=False)
    if spec.get("aia"):
        descriptions = []
        for item in spec["aia"]:
            method = ObjectIdentifier(str(item.get("method", "1.3.6.1.5.5.7.48.2")))
            descriptions.append(
                x509.AccessDescription(method, x509.UniformResourceIdentifier(str(item["uri"])))
            )
        builder = builder.add_extension(
            x509.AuthorityInformationAccess(descriptions), critical=False
        )
    if spec.get("crl_distribution_points"):
        points = [
            x509.DistributionPoint(
                full_name=[x509.UniformResourceIdentifier(str(uri))],
                relative_name=None,
                reasons=None,
                crl_issuer=None,
            )
            for uri in spec["crl_distribution_points"]
        ]
        builder = builder.add_extension(x509.CRLDistributionPoints(points), critical=False)
    if spec.get("policies"):
        policies = []
        for item in spec["policies"]:
            if isinstance(item, str):
                policies.append(x509.PolicyInformation(ObjectIdentifier(item), None))
            elif isinstance(item, dict):
                qualifiers = [str(value) for value in item.get("cps", [])]
                policies.append(
                    x509.PolicyInformation(ObjectIdentifier(str(item["oid"])), qualifiers or None)
                )
            else:
                raise MaterialError("certificate policies must be OID strings or mappings")
        builder = builder.add_extension(x509.CertificatePolicies(policies), critical=False)
    if spec.get("name_constraints"):
        constraints_spec = spec["name_constraints"]
        if not isinstance(constraints_spec, dict):
            raise MaterialError("name_constraints must be a mapping")
        builder = builder.add_extension(
            x509.NameConstraints(
                permitted_subtrees=_general_names(constraints_spec.get("permitted", {})) or None,
                excluded_subtrees=_general_names(constraints_spec.get("excluded", {})) or None,
            ),
            critical=True,
        )
    for extension in spec.get("extensions", []):
        oid = ObjectIdentifier(str(extension["oid"]))
        raw = extension.get("value", "")
        value = (
            base64.b64decode(raw) if extension.get("encoding") == "base64" else str(raw).encode()
        )
        builder = builder.add_extension(
            x509.UnrecognizedExtension(oid, value), critical=bool(extension.get("critical", False))
        )
    algorithm = (
        None
        if isinstance(
            issuer_key,
            (
                ed25519.Ed25519PrivateKey,
                ed448.Ed448PrivateKey,
                mldsa.MLDSA44PrivateKey,
                mldsa.MLDSA65PrivateKey,
                mldsa.MLDSA87PrivateKey,
            ),
        )
        else hashes.SHA256()
    )
    return builder.sign(issuer_key, algorithm)


def _subject(value: Any, default_cn: str) -> x509.Name:
    if not isinstance(value, dict):
        raise MaterialError("subject must be a mapping")
    mapping = (
        ("country", NameOID.COUNTRY_NAME),
        ("state", NameOID.STATE_OR_PROVINCE_NAME),
        ("locality", NameOID.LOCALITY_NAME),
        ("organization", NameOID.ORGANIZATION_NAME),
        ("organizational_unit", NameOID.ORGANIZATIONAL_UNIT_NAME),
        ("common_name", NameOID.COMMON_NAME),
        ("email", NameOID.EMAIL_ADDRESS),
        ("serial_number", NameOID.SERIAL_NUMBER),
        ("street_address", NameOID.STREET_ADDRESS),
        ("postal_code", NameOID.POSTAL_CODE),
        ("domain_component", NameOID.DOMAIN_COMPONENT),
        ("user_id", NameOID.USER_ID),
        ("title", NameOID.TITLE),
        ("given_name", NameOID.GIVEN_NAME),
        ("surname", NameOID.SURNAME),
    )
    attributes = [x509.NameAttribute(oid, str(value[key])) for key, oid in mapping if key in value]
    if "common_name" not in value:
        attributes.append(x509.NameAttribute(NameOID.COMMON_NAME, default_cn))
    return x509.Name(attributes)


def _certificate_time(value: Any, default: datetime) -> datetime:
    if value is None:
        return default
    if not isinstance(value, str):
        raise MaterialError("certificate times must be ISO-8601 strings")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MaterialError(f"invalid certificate time: {value!r}") from error
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _artifact_files(
    key: Any,
    cert: x509.Certificate,
    chain: tuple[x509.Certificate, ...],
    spec: dict[str, Any],
    *,
    include_private: bool,
) -> dict[str, bytes]:
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    files = {
        "certificate.pem": cert_pem,
        "public-key.pem": _public_bytes(key),
        "chain.pem": b"".join(item.public_bytes(serialization.Encoding.PEM) for item in chain[1:]),
        "full-chain.pem": b"".join(item.public_bytes(serialization.Encoding.PEM) for item in chain),
    }
    if include_private:
        files["private-key.pem"] = _private_bytes(key)
    formats = set(spec.get("formats", ["pem"]))
    if "der" in formats:
        files["certificate.der"] = cert.public_bytes(serialization.Encoding.DER)
    if "pkcs12" in formats:
        password = spec.get("pkcs12_password")
        encryption = (
            serialization.NoEncryption()
            if password is None
            else serialization.BestAvailableEncryption(str(password).encode())
        )
        files["identity.p12"] = pkcs12.serialize_key_and_certificates(
            cert.subject.rfc4514_string().encode(), key, cert, list(chain[1:]), encryption
        )
    if "jks" in formats:
        password = spec.get("jks_password")
        if not isinstance(password, str) or not password:
            raise MaterialError("JKS output requires jks_password")
        bundle = pkcs12.serialize_key_and_certificates(
            b"identity",
            key,
            cert,
            list(chain[1:]),
            serialization.BestAvailableEncryption(password.encode()),
        )
        files["identity.jks"] = _pkcs12_to_jks(bundle, password)
    unsupported = formats - {"pem", "der", "pkcs12", "jks"}
    if unsupported:
        raise MaterialError(f"unsupported output formats: {', '.join(sorted(unsupported))}")
    return files


def _private_bytes(key: Any) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _public_bytes(key: Any) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _load_chain(path: Path) -> tuple[x509.Certificate, ...]:
    if not path.is_file() or not path.read_bytes().strip():
        return ()
    return tuple(x509.load_pem_x509_certificates(path.read_bytes()))


def _general_names(value: Any) -> list[x509.GeneralName]:
    if not isinstance(value, dict):
        raise MaterialError("name-constraint subtree must be a mapping")
    result: list[x509.GeneralName] = []
    result.extend(x509.DNSName(str(item)) for item in value.get("dns", []))
    result.extend(x509.IPAddress(ipaddress.ip_network(item)) for item in value.get("ip", []))
    result.extend(x509.RFC822Name(str(item)) for item in value.get("email", []))
    result.extend(x509.UniformResourceIdentifier(str(item)) for item in value.get("uri", []))
    return result


def _pkcs12_to_jks(bundle: bytes, password: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix=".pki-jks-") as directory:
        root = Path(directory)
        source, target = root / "identity.p12", root / "identity.jks"
        source.write_bytes(bundle)
        try:
            environment = dict(os.environ)
            environment["ECLAB_PKI_JKS_PASSWORD"] = password
            subprocess.run(
                [
                    "keytool",
                    "-importkeystore",
                    "-noprompt",
                    "-srckeystore",
                    str(source),
                    "-srcstoretype",
                    "PKCS12",
                    "-srcstorepass:env",
                    "ECLAB_PKI_JKS_PASSWORD",
                    "-destkeystore",
                    str(target),
                    "-deststoretype",
                    "JKS",
                    "-deststorepass:env",
                    "ECLAB_PKI_JKS_PASSWORD",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=environment,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise MaterialError("JKS output requires a working keytool command") from error
        return target.read_bytes()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _atomic_directory(target: Path, files: dict[str, bytes]) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        os.chmod(work, 0o700)
        for relative, content in files.items():
            path = work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            os.chmod(path, 0o600 if "private" in relative or relative.endswith(".p12") else 0o644)
        work.replace(target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def rollback_created(paths: list[Path]) -> None:
    for path in reversed(paths):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
