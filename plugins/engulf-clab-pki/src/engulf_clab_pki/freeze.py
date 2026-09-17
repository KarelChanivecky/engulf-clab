from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from engulf_clab_freeze_api import DefrostContext, FreezeContext, FreezeError
from engulf_clab_lab_parser import TopologyError, effective_nodes, topology_declarations

from .catalog import load_catalog
from .plugin import MANIFEST_ENVIRONMENT


class PkiFreezeContributor:
    contributor_id = "engulf_clab.pki"

    def add_freeze_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--include-pki-secrets",
            action="store_true",
            help="include exportable PKI identities in an encrypted bundle",
        )
        parser.add_argument(
            "--pki-passphrase-file",
            metavar="FILE",
            help="read the PKI bundle passphrase from an owner-private file",
        )

    def add_defrost_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--pki-authority",
            action="append",
            metavar="BINDING=REF",
            help="resolve one frozen external authority binding",
        )
        parser.add_argument(
            "--no-pki-prompt",
            action="store_true",
            help="leave unresolved PKI bindings as actionable manifest markers",
        )
        parser.add_argument("--pki-passphrase-file", metavar="FILE")

    def freeze(self, context: FreezeContext) -> dict[str, Any] | None:
        document = _document(context.staged_topology)
        selector = _selector(document)
        if selector is None:
            return None
        original_selector = _selector(_document(context.source_topology))
        if original_selector is None:
            raise FreezeError("staged PKI topology lost its source selector")
        source_manifest = Path(original_selector).expanduser()
        if not source_manifest.is_absolute():
            source_manifest = context.source_topology.parent / source_manifest
        source_manifest = source_manifest.resolve()
        local = load_catalog(source_manifest, required=True)
        _sanitize_staged_state(context, local)
        portable = json.loads(json.dumps(local))
        redacted: list[str] = []
        _remove_secrets(portable, (), redacted)
        _vendor_global_certificate_declarations(portable, document, context.user_state)
        bindings = _external_bindings(portable, context.user_state, document)
        export_catalog = local
        export_locations: dict[str, Path] = {}
        if context.arguments.include_pki_secrets:
            export_catalog, export_locations = _preserve_global_bindings(
                local, portable, bindings, context.user_state
            )
        _portable_external_stores(
            local,
            portable,
            bindings,
            preserve_exportable=bool(context.arguments.include_pki_secrets),
        )
        destination = context.staging_root / "pki.yaml"
        destination.write_text(yaml.safe_dump(portable, sort_keys=False), encoding="utf-8")
        _set_selector(document, "./pki.yaml")
        context.staged_topology.write_text(
            yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
        )
        metadata: dict[str, Any] = {
            "manifest": "pki.yaml",
            "source": "vendored",
            "bindings": bindings,
            "local_authorities": {
                name: {
                    "intent": "regenerate",
                    "definition_sha256": hashlib.sha256(
                        json.dumps(spec, sort_keys=True, default=str).encode()
                    ).hexdigest(),
                }
                for name, spec in portable.get("authorities", {}).items()
            },
        }
        if redacted:
            metadata["redacted"] = sorted(redacted)
        if context.arguments.include_pki_secrets:
            passphrase = _passphrase(
                context.arguments.pki_passphrase_file, "Freeze PKI passphrase: "
            )
            exported = _exportable_material(
                export_catalog,
                context.workspace_state,
                context.user_state,
                authority_locations=export_locations,
                topology=document,
            )
            bundle = _encrypt(json.dumps(exported, sort_keys=True).encode(), passphrase)
            bundle_path = context.staging_root / ".eclab-pki-identities.enc"
            bundle_path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")
            os.chmod(bundle_path, 0o600)
            metadata["identity_bundle"] = bundle_path.name
            metadata["identity_fingerprints"] = _bundle_fingerprints(exported)
        return metadata

    def defrost(self, context: DefrostContext) -> None:
        document = _document(context.topology)
        manifest_name = context.metadata.get("manifest")
        if not isinstance(manifest_name, str):
            raise FreezeError("PKI freeze metadata has no manifest")
        manifest = context.staging_root / manifest_name
        local = load_catalog(manifest, required=True)
        answers = _binding_answers(context.arguments.pki_authority or [])
        bindings = context.metadata.get("bindings", {})
        unresolved: dict[str, Any] = {}
        if not isinstance(bindings, dict):
            raise FreezeError("PKI bindings metadata must be a mapping")
        global_catalog = (
            load_catalog(context.user_state / "global.yaml", global_scope=True)
            if context.user_state is not None
            else {"version": 2}
        )
        for name, binding in bindings.items():
            if not isinstance(binding, dict):
                raise FreezeError(f"invalid PKI binding {name!r}")
            expected = binding.get("fingerprint_sha256")
            answer = answers.get(name)
            if answer is None and expected:
                answer = _matching_global(global_catalog, str(expected), context.user_state)
            if answer is None and not context.arguments.no_pki_prompt:
                answer = (
                    input(f"PKI authority for {name} ({expected or 'new identity'}): ").strip()
                    or None
                )
            if answer is None:
                unresolved[name] = binding
                continue
            if expected:
                actual = _reference_fingerprint(answer, global_catalog, context.user_state)
                if actual != expected:
                    raise FreezeError(
                        f"PKI binding {name!r} requires fingerprint {expected}; "
                        f"{answer!r} does not match"
                    )
            _rewrite_authority_references(local, name, answer)
            _rewrite_topology_authority_references(document, name, answer)
        if unresolved:
            local["unresolved_bindings"] = unresolved
        manifest.write_text(yaml.safe_dump(local, sort_keys=False), encoding="utf-8")
        bundle_name = context.metadata.get("identity_bundle")
        if bundle_name is not None:
            if not isinstance(bundle_name, str):
                raise FreezeError("invalid PKI identity bundle name")
            passphrase = _passphrase(
                context.arguments.pki_passphrase_file, "Defrost PKI passphrase: "
            )
            payload = json.loads((context.staging_root / bundle_name).read_text(encoding="utf-8"))
            identities = json.loads(_decrypt(payload, passphrase))
            if _bundle_fingerprints(identities) != context.metadata.get("identity_fingerprints"):
                raise FreezeError("PKI identity bundle fingerprints do not match metadata")
            _restore_identities(identities, context.staging_root)
            stores = local.setdefault("stores", {})
            snapshot_definitions = {
                name: hashlib.sha256(
                    json.dumps(
                        {
                            key: value
                            for key, value in spec.items()
                            if key not in {"issuer", "variants", "store", "lifetime", "freeze"}
                        },
                        sort_keys=True,
                        default=str,
                    ).encode()
                ).hexdigest()
                for name, spec in local.get("authorities", {}).items()
                if isinstance(spec, dict)
            }
            stores["frozen-identities"] = {
                "type": "directory",
                "path": str((context.destination / ".eclab-pki-import" / "authorities").resolve()),
                "snapshot_definitions": snapshot_definitions,
            }
            for name in local.get("authorities", {}):
                local["authorities"][name]["store"] = "frozen-identities"
            _mark_restored_leaves(local, context.destination, identities, document)
            manifest.write_text(yaml.safe_dump(local, sort_keys=False), encoding="utf-8")
            (context.staging_root / bundle_name).unlink(missing_ok=True)
        _set_selector(document, "./pki.yaml")
        context.topology.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _document(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FreezeError("PKI topology must contain a mapping")
    return value


def _selector(document: dict[str, Any]) -> str | None:
    defaults = document.get("topology", {}).get("defaults", {})
    env = defaults.get("env", {}) if isinstance(defaults, dict) else {}
    value = env.get(MANIFEST_ENVIRONMENT) if isinstance(env, dict) else None
    return value if isinstance(value, str) else None


def _set_selector(document: dict[str, Any], value: str) -> None:
    topology = document.setdefault("topology", {})
    defaults = topology.setdefault("defaults", {})
    environment = defaults.setdefault("env", {})
    environment[MANIFEST_ENVIRONMENT] = value


def _sanitize_staged_state(context: FreezeContext, local: dict[str, Any]) -> None:
    managed = [context.source_root / ".eclab-pki-import"]
    if context.workspace_state is not None:
        managed.append(context.workspace_state)
    for store in local.get("stores", {}).values():
        if not isinstance(store, dict) or store.get("type") != "directory":
            continue
        path_value = store.get("path")
        if isinstance(path_value, str):
            managed.append(Path(path_value).expanduser().resolve())
    source_root = context.source_root.resolve()
    for source in managed:
        try:
            relative = source.resolve().relative_to(source_root)
        except ValueError:
            continue
        if not relative.parts:
            raise FreezeError("PKI managed state must not be the lab source root")
        staged = context.staging_root / relative
        if staged.is_symlink() or staged.is_file():
            staged.unlink()
        elif staged.is_dir():
            shutil.rmtree(staged)


def _external_bindings(
    local: dict[str, Any],
    user_state: Path | None,
    topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global_catalog = (
        load_catalog(user_state / "global.yaml", global_scope=True)
        if user_state is not None and (user_state / "global.yaml").is_file()
        else {"version": 2}
    )
    local_authorities = local.get("authorities", {})
    global_authorities: Any = global_catalog.get("authorities", {})
    local_names = set(local_authorities if isinstance(local_authorities, dict) else {})
    global_names = set(global_authorities if isinstance(global_authorities, dict) else {})
    references: set[str] = set()

    def collect(reference: Any) -> None:
        if not isinstance(reference, str):
            return
        parts = reference.split("/")
        if parts[0] == "global" and len(parts) >= 2:
            references.add(parts[1])
        elif (
            parts[0] not in {"local", "global"}
            and parts[0] not in local_names
            and parts[0] in global_names
        ):
            references.add(parts[0])

    for spec in local.get("authorities", {}).values():
        if isinstance(spec, dict):
            candidates = [spec.get("issuer")]
            candidates.extend(
                value.get("issuer")
                for value in spec.get("variants", {}).values()
                if isinstance(value, dict)
            )
            for value in candidates:
                collect(value)
    for spec in local.get("certificates", {}).values():
        if isinstance(spec, dict):
            collect(spec.get("issuer"))
    if topology is not None:
        for variable in (
            "ECLAB_PKI_PRIVATE_AUTHORITIES",
            "ECLAB_PKI_TRUST_INCLUDE",
            "ECLAB_PKI_TRUST_EXCLUDE",
        ):
            for _node, reference in _topology_environment_requests(topology, variable):
                collect(reference)
    for node in local.get("nodes", {}).values():
        if isinstance(node, dict):
            for value in node.get("certificates", []):
                if isinstance(value, dict):
                    collect(value.get("issuer"))
            for value in node.get("authorities", []):
                collect(
                    value
                    if isinstance(value, str)
                    else value.get("name")
                    if isinstance(value, dict)
                    else None
                )
    result: dict[str, Any] = {}
    for name in sorted(references):
        fingerprint = _material_fingerprint(user_state, name)
        result[name] = {
            "kind": "authority",
            "fingerprint_sha256": fingerprint,
            "intent": "binding" if fingerprint else "regenerate-new-identity",
        }
        chain = _material_chain(user_state, name)
        if chain is not None:
            result[name]["public_chain_pem"] = chain
    return result


def _remove_secrets(value: Any, path: tuple[str, ...], redacted: list[str]) -> None:
    if isinstance(value, dict):
        for key in tuple(value):
            normalized = str(key).lower().replace("-", "_")
            current = (*path, str(key))
            if any(
                marker in normalized
                for marker in (
                    "password",
                    "passphrase",
                    "secret",
                    "credential",
                    "private_key",
                    "token",
                )
            ):
                value.pop(key)
                redacted.append(".".join(current))
            else:
                _remove_secrets(value[key], current, redacted)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _remove_secrets(item, (*path, str(index)), redacted)


def _vendor_global_certificate_declarations(
    portable: dict[str, Any], document: dict[str, Any], user_state: Path | None
) -> None:
    if user_state is None or not (user_state / "global.yaml").is_file():
        return
    global_catalog = load_catalog(user_state / "global.yaml", global_scope=True)
    portable["defaults"] = _merge_mappings(
        global_catalog.get("defaults", {}), portable.get("defaults", {})
    )
    global_certificates = global_catalog.get("certificates", {})
    global_profiles = global_catalog.get("profiles", {})
    local_certificates = portable.setdefault("certificates", {})
    local_profiles = portable.setdefault("profiles", {})
    if not all(
        isinstance(value, dict)
        for value in (global_certificates, global_profiles, local_certificates, local_profiles)
    ):
        return
    replacements: dict[str, str] = {}
    for _node, reference in _topology_certificate_requests(document):
        parts = reference.split("/")
        explicit_global = len(parts) == 2 and parts[0] == "global"
        name = parts[-1]
        if not explicit_global and name in local_certificates:
            continue
        definition = global_certificates.get(name)
        if not isinstance(definition, dict):
            continue
        target = name if name not in local_certificates else f"frozen-global-{name}"
        copied = json.loads(json.dumps(definition))
        issuer = copied.get("issuer")
        if isinstance(issuer, str) and not issuer.startswith(("global/", "local/")):
            copied["issuer"] = f"global/{issuer}"
        profile = copied.get("profile")
        if isinstance(profile, str) and profile != "tls-peer":
            profile_name = profile.split("/", 1)[-1]
            profile_definition = global_profiles.get(profile_name)
            if isinstance(profile_definition, dict):
                profile_target = (
                    profile_name
                    if profile_name not in local_profiles
                    else f"frozen-global-{profile_name}"
                )
                local_profiles[profile_target] = json.loads(json.dumps(profile_definition))
                copied["profile"] = f"local/{profile_target}"
        local_certificates[target] = copied
        replacements[reference] = f"local/{target}"
    if not replacements:
        return
    _rewrite_topology_environment_references(
        document,
        "ECLAB_PKI_CERTIFICATES",
        lambda item: replacements.get(item, item),
    )


def _merge_mappings(base: Any, override: Any) -> dict[str, Any]:
    result = json.loads(json.dumps(base)) if isinstance(base, dict) else {}
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge_mappings(result[key], value)
        else:
            result[key] = json.loads(json.dumps(value))
    return result


def _portable_external_stores(
    original: dict[str, Any],
    portable: dict[str, Any],
    bindings: dict[str, Any],
    *,
    preserve_exportable: bool = False,
) -> None:
    stores = original.get("stores", {})
    authorities = original.get("authorities", {})
    portable_authorities = portable.get("authorities", {})
    portable_stores = portable.get("stores", {})
    if not all(
        isinstance(value, dict)
        for value in (stores, authorities, portable_authorities, portable_stores)
    ):
        return
    for name, spec in authorities.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("store"), str):
            continue
        store_name = spec["store"]
        store = stores.get(store_name)
        if not isinstance(store, dict) or store.get("type") != "directory":
            continue
        path_value = store.get("path")
        if not isinstance(path_value, str):
            continue
        store_root = Path(path_value).expanduser()
        fingerprint = _material_fingerprint_at(store_root, str(name))
        if fingerprint is None:
            portable_spec = portable_authorities.get(name)
            if isinstance(portable_spec, dict):
                portable_spec.pop("store", None)
            portable_stores.pop(store_name, None)
            continue
        portable_spec = portable_authorities.get(name)
        if preserve_exportable and bool(spec.get("freeze", {}).get("exportable", False)):
            if isinstance(portable_spec, dict):
                portable_spec.pop("store", None)
            portable_stores.pop(store_name, None)
            continue
        binding = {
            "kind": "authority",
            "fingerprint_sha256": fingerprint,
            "intent": "binding",
            "local_definition": True,
        }
        chain = _material_chain_at(store_root, str(name))
        if chain is not None:
            binding["public_chain_pem"] = chain
        bindings[str(name)] = binding
        portable_authorities.pop(name, None)
        portable_stores.pop(store_name, None)


def _preserve_global_bindings(
    local: dict[str, Any],
    portable: dict[str, Any],
    bindings: dict[str, Any],
    user_state: Path | None,
) -> tuple[dict[str, Any], dict[str, Path]]:
    if not bindings:
        return local, {}
    if user_state is None:
        raise FreezeError("global PKI identities cannot be preserved without user state")
    global_catalog = load_catalog(user_state / "global.yaml", global_scope=True)
    global_authorities = global_catalog.get("authorities", {})
    local_names = set(local.get("authorities", {}))
    requested = {name for name in bindings if name in global_authorities}
    if requested & local_names:
        names = ", ".join(sorted(requested & local_names))
        raise FreezeError(
            "cannot preserve shadowed global PKI identities without distinct names: " + names
        )
    queue = list(requested)
    included: set[str] = set()
    while queue:
        name = queue.pop()
        if name in included:
            continue
        spec = global_authorities.get(name)
        if not isinstance(spec, dict):
            raise FreezeError(f"missing global authority definition {name!r}")
        included.add(name)
        issuers = [spec.get("issuer")]
        issuers.extend(
            variant.get("issuer")
            for variant in spec.get("variants", {}).values()
            if isinstance(variant, dict)
        )
        for reference in issuers:
            if not isinstance(reference, str):
                continue
            parts = reference.split("/")
            dependency = parts[1] if parts[0] == "global" and len(parts) > 1 else parts[0]
            if dependency in global_authorities:
                if dependency in local_names:
                    raise FreezeError(
                        "cannot preserve a global PKI issuer shadowed locally: " + dependency
                    )
                queue.append(dependency)
    refused = sorted(
        name
        for name in included
        if not bool(global_authorities[name].get("freeze", {}).get("exportable", False))
    )
    if refused:
        raise FreezeError(
            "non-exportable PKI identities: "
            + ", ".join(f"authority:global/{name}" for name in refused)
        )
    export_catalog = json.loads(json.dumps(local))
    portable_authorities = portable.setdefault("authorities", {})
    export_authorities = export_catalog.setdefault("authorities", {})
    locations: dict[str, Path] = {}
    for name in sorted(included):
        definition = json.loads(json.dumps(global_authorities[name]))
        definition.pop("store", None)
        portable_authorities[name] = definition
        export_authorities[name] = definition
        location = user_state / "pki" / "authorities" / name
        if not location.is_dir():
            raise FreezeError(f"exportable global authority {name!r} has no existing material")
        locations[name] = location
        bindings.pop(name, None)
        _rewrite_authority_references(portable, name, f"local/{name}")
    return export_catalog, locations


def _material_fingerprint(state: Path | None, name: str) -> str | None:
    if state is None:
        return None
    return _material_fingerprint_at(state / "pki" / "authorities", name)


def _material_fingerprint_at(root: Path, name: str) -> str | None:
    generations = root / name / "generations" / "default"
    if not generations.is_dir():
        return None
    certificates = sorted(
        generations.glob("*/certificate.pem"), key=lambda item: item.stat().st_mtime, reverse=True
    )
    if not certificates:
        return None
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    return (
        x509.load_pem_x509_certificate(certificates[0].read_bytes())
        .fingerprint(hashes.SHA256())
        .hex()
    )


def _material_chain(state: Path | None, name: str) -> str | None:
    if state is None:
        return None
    return _material_chain_at(state / "pki" / "authorities", name)


def _material_chain_at(root: Path, name: str) -> str | None:
    generations = root / name / "generations" / "default"
    if not generations.is_dir():
        return None
    chains = sorted(
        generations.glob("*/full-chain.pem"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return chains[0].read_text(encoding="utf-8") if chains else None


def _passphrase(filename: str | None, prompt: str) -> bytes:
    if filename:
        path = Path(filename).expanduser().resolve()
        if path.is_symlink() or not path.is_file():
            raise FreezeError("PKI passphrase file is not a regular file")
        if path.stat().st_mode & 0o077:
            raise FreezeError("PKI passphrase file must not be accessible by group or others")
        value = path.read_bytes().rstrip(b"\r\n")
    elif sys_stdin_tty():
        value = getpass.getpass(prompt).encode()
    else:
        raise FreezeError(
            "PKI identity preservation requires --pki-passphrase-file or an interactive terminal"
        )
    if not value:
        raise FreezeError("PKI passphrase must not be empty")
    return value


def sys_stdin_tty() -> bool:
    import sys

    return sys.stdin.isatty()


def _encrypt(plaintext: bytes, passphrase: bytes) -> dict[str, Any]:
    salt, nonce = os.urandom(16), os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, b"engulf-clab-pki-v1")
    return {
        "version": 1,
        "kdf": "scrypt",
        "cipher": "aes-256-gcm",
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def _decrypt(payload: dict[str, Any], passphrase: bytes) -> bytes:
    try:
        salt = base64.b64decode(payload["salt"], validate=True)
        nonce = base64.b64decode(payload["nonce"], validate=True)
        ciphertext = base64.b64decode(payload["ciphertext"], validate=True)
        key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase)
        return AESGCM(key).decrypt(nonce, ciphertext, b"engulf-clab-pki-v1")
    except Exception as error:
        raise FreezeError("PKI identity bundle authentication failed") from error


def _exportable_material(
    local: dict[str, Any],
    workspace: Path | None,
    user: Path | None,
    *,
    authority_locations: dict[str, Path] | None = None,
    topology: dict[str, Any] | None = None,
) -> dict[str, str]:
    refused: list[str] = []
    exported: dict[str, str] = {}
    for name, spec in local.get("authorities", {}).items():
        if not isinstance(spec, dict) or not bool(spec.get("freeze", {}).get("exportable", False)):
            refused.append(f"authority:{name}")
            continue
        authority_root = (authority_locations or {}).get(name)
        store_name = spec.get("store")
        store = local.get("stores", {}).get(store_name) if isinstance(store_name, str) else None
        if isinstance(store, dict) and store.get("type") == "directory":
            store_path = store.get("path")
            if isinstance(store_path, str):
                candidate = Path(store_path).expanduser().resolve() / name
                authority_root = candidate if candidate.is_dir() else None
        if authority_root is None:
            roots = [item for item in (workspace, user) if item is not None]
            authority_root = next(
                (
                    root / "pki" / "authorities" / name
                    for root in roots
                    if (root / "pki" / "authorities" / name).is_dir()
                ),
                None,
            )
        if authority_root is None:
            raise FreezeError(f"exportable authority {name!r} has no existing material")
        for file in authority_root.rglob("*"):
            if file.is_file():
                exported[
                    f".eclab-pki-import/authorities/{name}/{file.relative_to(authority_root)}"
                ] = base64.b64encode(file.read_bytes()).decode()
    for node, reference in _topology_certificate_requests(topology or {}):
        reference_parts = reference.split("/")
        scope = (
            reference_parts[0]
            if len(reference_parts) == 2 and reference_parts[0] in {"local", "global"}
            else "local"
        )
        name = reference_parts[-1]
        request = local.get("certificates", {}).get(name)
        if scope != "local" or not isinstance(request, dict):
            refused.append(f"leaf:{node}/{scope}/{name}")
            continue
        if not bool(request.get("freeze", {}).get("exportable", False)):
            refused.append(f"leaf:{node}/local/{name}")
            continue
        if workspace is None:
            raise FreezeError(f"exportable leaf {node}/local/{name} has no workspace state")
        source = workspace / "pki" / "issued" / str(node) / "local" / name
        generations = (
            sorted(source.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True)
            if source.is_dir()
            else []
        )
        if not generations:
            raise FreezeError(f"exportable leaf {node}/local/{name} has no existing material")
        for file in generations[0].rglob("*"):
            if file.is_file():
                exported[
                    f".eclab-pki-import/issued/{node}/local/{name}/{generations[0].name}/"
                    f"{file.relative_to(generations[0])}"
                ] = base64.b64encode(file.read_bytes()).decode()
    if refused:
        raise FreezeError("non-exportable PKI identities: " + ", ".join(sorted(refused)))
    return exported


def _mark_restored_leaves(
    local: dict[str, Any],
    destination: Path,
    identities: dict[str, str],
    topology: dict[str, Any],
) -> None:
    prefix = (".eclab-pki-import", "issued")
    generations: dict[tuple[str, str, str], str] = {}
    for relative in identities:
        parts = Path(relative).parts
        if len(parts) == 7 and parts[:2] == prefix and parts[-1] == "certificate.pem":
            generations[(parts[2], parts[3], parts[4])] = parts[5]
    for node, reference in _topology_certificate_requests(topology):
        reference_parts = reference.split("/")
        scope = (
            reference_parts[0]
            if len(reference_parts) == 2 and reference_parts[0] in {"local", "global"}
            else "local"
        )
        name = reference_parts[-1]
        request = local.get("certificates", {}).get(name)
        if scope != "local" or not isinstance(request, dict):
            continue
        generation = generations.get((str(node), scope, name))
        if generation is None:
            continue
        definition = {
            key: value
            for key, value in request.items()
            if key not in {"freeze", "restored_snapshot", "restored_snapshots"}
        }
        request.setdefault("restored_snapshots", {})[str(node)] = {
            "path": str(
                (
                    destination
                    / ".eclab-pki-import"
                    / "issued"
                    / str(node)
                    / scope
                    / name
                    / generation
                ).resolve()
            ),
            "definition_sha256": hashlib.sha256(
                json.dumps(definition, sort_keys=True, default=str).encode()
            ).hexdigest(),
        }


def _topology_certificate_requests(topology: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return _topology_environment_requests(topology, "ECLAB_PKI_CERTIFICATES")


def _topology_environment_requests(
    topology: dict[str, Any], variable: str
) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    try:
        nodes = effective_nodes(topology)
    except TopologyError as error:
        raise FreezeError(f"could not resolve inherited topology settings: {error}") from error
    for node in nodes:
        environment = node.data.get("env", {})
        value = environment.get(variable) if isinstance(environment, Mapping) else None
        if isinstance(value, str):
            result.extend(
                (node.name, item.strip()) for item in value.split(",") if item.strip()
            )
    return tuple(result)


def _rewrite_topology_environment_references(
    document: dict[str, Any],
    variable: str,
    rewrite: Callable[[str], str],
) -> None:
    """Rewrite one topology env variable at every declaration origin.

    Effective values identify which requests are used, but the source topology
    must be independent of the exporting machine as a whole. Rewrite shadowed
    and unused declarations too, so a later kind/group selection cannot restore
    an old site-specific authority reference.
    """
    for declaration in topology_declarations(document):
        owner: Any = document
        for part in declaration.origin.path:
            owner = owner[part]
        environment = owner.get("env") if isinstance(owner, dict) else None
        if not isinstance(environment, dict):
            continue
        value = environment.get(variable)
        if not isinstance(value, str):
            continue
        environment[variable] = ",".join(
            rewrite(item.strip()) for item in value.split(",")
        )


def _binding_answers(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, reference = value.partition("=")
        if not separator or not name or not reference:
            raise FreezeError("--pki-authority requires BINDING=REF")
        result[name] = reference
    return result


def _matching_global(
    catalog: dict[str, Any], fingerprint: str, user_state: Path | None
) -> str | None:
    for name in catalog.get("authorities", {}):
        if _material_fingerprint(user_state, name) == fingerprint:
            return f"global/{name}"
    return None


def _reference_fingerprint(
    reference: str, catalog: dict[str, Any], user_state: Path | None
) -> str | None:
    parts = reference.split("/")
    if parts and parts[0] == "global":
        parts.pop(0)
    if len(parts) not in {1, 2} or parts[0] not in catalog.get("authorities", {}):
        return None
    # Material fingerprint lookup currently selects the default variant. An
    # explicit alternate variant is never treated as an unverifiable match.
    if len(parts) == 2 and parts[1] != "default":
        return None
    return _material_fingerprint(user_state, parts[0])


def _rewrite_authority_references(
    value: Any, binding: str, replacement: str, *, parent_key: str | None = None
) -> None:
    if isinstance(value, dict):
        for key, item in tuple(value.items()):
            if key in {"issuer", "name"} and isinstance(item, str):
                value[key] = _rewritten_reference(item, binding, replacement)
            else:
                _rewrite_authority_references(item, binding, replacement, parent_key=str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if parent_key == "authorities" and isinstance(item, str):
                value[index] = _rewritten_reference(item, binding, replacement)
            else:
                _rewrite_authority_references(item, binding, replacement)


def _rewrite_topology_authority_references(
    document: dict[str, Any], binding: str, replacement: str
) -> None:
    for variable in (
        "ECLAB_PKI_PRIVATE_AUTHORITIES",
        "ECLAB_PKI_TRUST_INCLUDE",
        "ECLAB_PKI_TRUST_EXCLUDE",
    ):
        _rewrite_topology_environment_references(
            document,
            variable,
            lambda item: _rewritten_reference(item, binding, replacement),
        )


def _rewritten_reference(value: str, binding: str, replacement: str) -> str:
    if value == binding or value.startswith(f"{binding}/"):
        return replacement + value[len(binding) :]
    qualified = f"global/{binding}"
    if value == qualified or value.startswith(f"{qualified}/"):
        return replacement + value[len(qualified) :]
    return value


def _restore_identities(identities: dict[str, str], destination: Path) -> None:
    decoded: list[tuple[Path, bytes]] = []
    for relative_name, encoded in identities.items():
        path = Path(relative_name)
        if path.is_absolute() or ".." in path.parts:
            raise FreezeError("PKI identity bundle contains an unsafe path")
        decoded.append((path, base64.b64decode(encoded, validate=True)))
    decoded_by_path = {path: content for path, content in decoded}
    for path, content in decoded:
        if path.name != "private-key.pem":
            continue
        private_key = serialization.load_pem_private_key(content, None)
        public_path = path.with_name("public-key.pem")
        certificate_path = path.with_name("certificate.pem")
        expected_public = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if public_path in decoded_by_path:
            public_key = serialization.load_pem_public_key(decoded_by_path[public_path])
            if (
                public_key.public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                != expected_public
            ):
                raise FreezeError("PKI identity bundle has a mismatched public key")
        if certificate_path in decoded_by_path:
            certificate = x509.load_pem_x509_certificate(decoded_by_path[certificate_path])
            if (
                certificate.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                != expected_public
            ):
                raise FreezeError("PKI identity bundle has a mismatched certificate")
    for path, content in decoded:
        if path.name != "certificate.pem" or "authorities" not in path.parts:
            continue
        authority_index = path.parts.index("authorities")
        if authority_index + 1 >= len(path.parts):
            raise FreezeError("PKI authority certificate has an invalid bundle path")
        authority_prefix = Path(*path.parts[: authority_index + 2])
        public_candidates = [
            value
            for candidate, value in decoded
            if candidate.parent.parent == authority_prefix / "identities"
            and candidate.name == "public-key.pem"
        ]
        certificate = x509.load_pem_x509_certificate(content)
        certificate_public = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if not any(
            serialization.load_pem_public_key(candidate).public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            == certificate_public
            for candidate in public_candidates
        ):
            raise FreezeError("PKI identity bundle has a mismatched authority certificate")
    for restored_relative, content in decoded:
        restored_path = destination / restored_relative
        restored_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        restored_path.write_bytes(content)
        os.chmod(restored_path, 0o600)


def _bundle_fingerprints(identities: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative, encoded in identities.items():
        if not relative.endswith("certificate.pem"):
            continue
        try:
            certificate = x509.load_pem_x509_certificate(base64.b64decode(encoded, validate=True))
        except Exception as error:
            raise FreezeError(f"invalid certificate in PKI identity bundle: {relative}") from error
        result[relative] = certificate.fingerprint(hashes.SHA256()).hex()
    return result


contributor = PkiFreezeContributor()
