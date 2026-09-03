from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization

from .catalog import CatalogError, EffectiveCatalog
from .material import MaterialSet

MOUNT_TARGET = "/mnt/eclab/pki"


def build_views(
    catalog: EffectiveCatalog, material: MaterialSet, workspace_root: Path
) -> tuple[dict[str, Path], list[Path]]:
    identity = hashlib.sha256(
        json.dumps(catalog.public_graph(), sort_keys=True, default=str).encode()
    ).hexdigest()[:20]
    root = workspace_root / "pki" / "views" / identity
    created: list[Path] = []
    views: dict[str, Path] = {}
    all_nodes = set(catalog.nodes)
    topology_nodes = catalog.local_catalog.get("_topology_nodes", [])
    all_nodes.update(str(item) for item in topology_nodes)
    for node in sorted(all_nodes):
        target = root / node
        if not target.exists():
            _build_view(target, node, catalog, material)
            created.append(target)
        views[node] = target
    return views, created


def _build_view(target: Path, node: str, catalog: EffectiveCatalog, material: MaterialSet) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = Path(tempfile.mkdtemp(prefix=f".{node}.", dir=target.parent))
    inventory: dict[str, Any] = {"version": 1, "authorities": [], "issued": []}
    try:
        os.chmod(work, 0o700)
        effective_names = catalog.origins["authorities"]
        bundle: list[bytes] = []
        for (scope, name, variant), item in sorted(material.authorities.items()):
            public = work / "authorities" / scope / name / variant
            _copy_public(item.directory, public)
            if effective_names.get(name) == scope:
                alias = work / "authorities" / "effective" / name / variant
                _copy_public(item.directory, alias)
                bundle.append(item.certificate.public_bytes(serialization.Encoding.PEM))
            inventory["authorities"].append(
                {
                    "origin": scope,
                    "name": name,
                    "variant": variant,
                    "fingerprint_sha256": item.fingerprint,
                    "formats": _formats(item.directory),
                    "path": str(Path("authorities") / scope / name / variant),
                }
            )
        trust = work / "trust"
        trust.mkdir(parents=True, exist_ok=True)
        (trust / "ca-bundle.pem").write_bytes(b"".join(bundle))
        requests = catalog.nodes.get(node, {})
        for request in requests.get("certificates", []):
            name = request["name"]
            leaf = material.leaves[(node, name)]
            destination = work / "issued" / node / name
            _copy_all(leaf.directory, destination)
            inventory["issued"].append(
                {
                    "node": node,
                    "name": name,
                    "fingerprint_sha256": leaf.fingerprint,
                    "formats": _formats(leaf.directory),
                    "path": str(Path("issued") / node / name),
                }
            )
        for request in requests.get("authorities", []):
            if isinstance(request, str):
                reference, private = request, False
            elif isinstance(request, dict) and isinstance(request.get("name"), str):
                reference, private = request["name"], bool(request.get("private", False))
            else:
                raise CatalogError(f"nodes.{node}.authorities entries require a name")
            scope, name, variant, _ = catalog.resolve_authority(reference)
            authority = material.authorities[(scope, name, variant)]
            if private:
                private_dir = work / "private" / "authorities" / scope / name / variant
                private_dir.mkdir(parents=True, exist_ok=True)
                (private_dir / "private-key.pem").write_bytes(
                    authority.private_key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                )
                os.chmod(private_dir / "private-key.pem", 0o600)
        (work / "inventory.json").write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for directory in work.rglob("*"):
            if directory.is_dir():
                os.chmod(directory, 0o755)
        work.replace(target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def _copy_public(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in (
        "certificate.pem",
        "public-key.pem",
        "chain.pem",
        "full-chain.pem",
        "certificate.der",
    ):
        candidate = source / name
        if candidate.is_file():
            shutil.copyfile(candidate, target / name)


def _copy_all(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for candidate in source.iterdir():
        if candidate.is_file():
            shutil.copyfile(candidate, target / candidate.name)
            os.chmod(
                target / candidate.name,
                0o600 if "private" in candidate.name or candidate.suffix == ".p12" else 0o644,
            )


def _formats(source: Path) -> list[str]:
    formats = ["pem"]
    if any(source.glob("*.der")):
        formats.append("der")
    if any(source.glob("*.p12")):
        formats.append("pkcs12")
    if any(source.glob("*.jks")):
        formats.append("jks")
    return formats


def incompatible_mount(node: dict[str, Any], target: str = MOUNT_TARGET) -> bool:
    binds = node.get("binds", [])
    if binds is None:
        return False
    if not isinstance(binds, list):
        raise CatalogError("node binds must be a list")
    for bind in binds:
        if isinstance(bind, str):
            parts = bind.split(":")
            if len(parts) >= 2 and parts[1] == target:
                return True
        elif isinstance(bind, dict) and bind.get("target") == target:
            return True
    return False


def cleanup_views(paths: list[Path]) -> None:
    for path in reversed(paths):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
