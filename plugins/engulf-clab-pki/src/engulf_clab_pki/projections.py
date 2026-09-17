from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from engulf_clab_lab_parser import effective_nodes
from engulf_clab_pki_api import (
    AuthorityClassification,
    IssuedIdentityProjection,
    NodePkiProjection,
    PkiNodeProjections,
    ProjectedFile,
    PublicAuthorityProjection,
    RequestedAuthorityProjection,
)

from .catalog import CatalogError, EffectiveCatalog, Scope
from .material import AuthorityMaterial, LeafMaterial, MaterialSet


def build_node_projections(
    catalog: EffectiveCatalog,
    material: MaterialSet,
    topology: dict[str, Any],
    views: dict[str, Path],
    mount_targets: dict[str, PurePosixPath],
) -> PkiNodeProjections:
    projected: list[NodePkiProjection] = []
    for node in sorted(effective_nodes(topology), key=lambda item: item.name):
        name = node.name
        view = views[name].absolute()
        mount = mount_targets[name]
        projected.append(
            NodePkiProjection(
                node_name=name,
                node_kind=_node_kind(node.data),
                staged_view=view,
                mount_target=mount,
                public_authorities=_public_authorities(catalog, material, view, mount),
                trusted_authorities=_trusted_authorities(
                    name, catalog, material, view, mount
                ),
                requested_authorities=_requested_authorities(
                    name, catalog, material, view, mount
                ),
                issued_identities=_issued_identities(name, catalog, material, view, mount),
            )
        )
    return PkiNodeProjections(tuple(projected))


def _node_kind(node: Mapping[str, Any]) -> str:
    value = node.get("kind")
    if value is None:
        return "linux"
    if not isinstance(value, str) or not value:
        raise CatalogError("topology node kind must be a nonempty string")
    return value


def _file(view: Path, mount: PurePosixPath, relative: PurePosixPath) -> ProjectedFile:
    return ProjectedFile(view.joinpath(*relative.parts), mount / relative)


def _public_projection(
    catalog: EffectiveCatalog,
    item: AuthorityMaterial,
    view: Path,
    mount: PurePosixPath,
) -> PublicAuthorityProjection:
    relative = PurePosixPath("authorities", item.scope, item.name, item.variant)
    return PublicAuthorityProjection(
        item.scope,
        item.name,
        item.variant,
        item.fingerprint,
        (
            AuthorityClassification.INTERMEDIATE
            if _authority_has_issuer(catalog, item.scope, item.name, item.variant)
            else AuthorityClassification.TRUST_ANCHOR
        ),
        _file(view, mount, relative / "certificate.pem"),
        _file(view, mount, relative / "chain.pem"),
        _file(view, mount, relative / "full-chain.pem"),
    )


def _public_authorities(
    catalog: EffectiveCatalog,
    material: MaterialSet,
    view: Path,
    mount: PurePosixPath,
) -> tuple[PublicAuthorityProjection, ...]:
    values = [
        _public_projection(catalog, item, view, mount)
        for (scope, name, _variant), item in sorted(material.authorities.items())
    ]
    return tuple(values)


def _trusted_authorities(
    node: str,
    catalog: EffectiveCatalog,
    material: MaterialSet,
    view: Path,
    mount: PurePosixPath,
) -> tuple[PublicAuthorityProjection, ...]:
    values: list[PublicAuthorityProjection] = []
    for reference in catalog.nodes.get(node, {}).get("trusted_authorities", []):
        scope, name, variant, _ = catalog.resolve_authority(reference)
        values.append(
            _public_projection(catalog, material.authorities[(scope, name, variant)], view, mount)
        )
    return tuple(_deduplicate(values, lambda item: item.fingerprint_sha256))


def _requested_authorities(
    node: str,
    catalog: EffectiveCatalog,
    material: MaterialSet,
    view: Path,
    mount: PurePosixPath,
) -> tuple[RequestedAuthorityProjection, ...]:
    candidates: list[RequestedAuthorityProjection] = []
    for request in catalog.nodes.get(node, {}).get("authorities", []):
        if isinstance(request, str):
            reference, private = request, False
        elif isinstance(request, dict) and isinstance(request.get("name"), str):
            reference, private = request["name"], bool(request.get("private", False))
        else:
            raise CatalogError(f"nodes.{node}.authorities entries require a name")
        if not private:
            continue
        scope, name, variant, _spec = catalog.resolve_authority(reference)
        item = material.authorities[(scope, name, variant)]
        relative = PurePosixPath("authorities", scope, name, variant)
        private_relative = PurePosixPath("private", "authorities", scope, name, variant)
        candidates.append(
            RequestedAuthorityProjection(
                scope,
                name,
                variant,
                item.fingerprint,
                _file(view, mount, relative / "certificate.pem"),
                _file(view, mount, relative / "chain.pem"),
                _file(view, mount, relative / "full-chain.pem"),
                _file(view, mount, private_relative / "private-key.pem") if private else None,
            )
        )
    grouped: dict[str, list[RequestedAuthorityProjection]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.fingerprint_sha256, []).append(candidate)
    result: list[RequestedAuthorityProjection] = []
    for fingerprint in sorted(grouped):
        group = sorted(grouped[fingerprint], key=_authority_key)
        canonical = group[0]
        private_key = next(
            (item.private_key for item in group if item.private_key is not None), None
        )
        result.append(
            RequestedAuthorityProjection(
                canonical.scope,
                canonical.name,
                canonical.variant,
                canonical.fingerprint_sha256,
                canonical.certificate,
                canonical.chain,
                canonical.full_chain,
                private_key,
            )
        )
    return tuple(sorted(result, key=_authority_key))


def _issued_identities(
    node: str,
    catalog: EffectiveCatalog,
    material: MaterialSet,
    view: Path,
    mount: PurePosixPath,
) -> tuple[IssuedIdentityProjection, ...]:
    values: list[IssuedIdentityProjection] = []
    for request in catalog.nodes.get(node, {}).get("certificates", []):
        name = request["name"]
        item: LeafMaterial = material.leaves[(node, name)]
        relative = PurePosixPath("issued", node, name)
        values.append(
            IssuedIdentityProjection(
                name,
                item.fingerprint,
                _file(view, mount, relative / "certificate.pem"),
                _file(view, mount, relative / "private-key.pem"),
                _file(view, mount, relative / "chain.pem"),
                _file(view, mount, relative / "full-chain.pem"),
            )
        )
    return tuple(sorted(values, key=lambda item: (item.request_name, item.fingerprint_sha256)))


def _authority_has_issuer(catalog: EffectiveCatalog, scope: Scope, name: str, variant: str) -> bool:
    source = catalog.global_catalog if scope == "global" else catalog.local_catalog
    spec = source["authorities"][name]
    variant_spec = spec.get("variants", {}).get(variant, {}) if variant != "default" else {}
    return variant_spec.get("issuer", spec.get("issuer")) is not None


def _authority_key(item: RequestedAuthorityProjection) -> tuple[str, str, str, str]:
    return item.scope, item.name, item.variant, item.fingerprint_sha256


def _deduplicate[T](values: list[T], key: Callable[[T], str]) -> list[T]:
    seen: set[str] = set()
    result: list[T] = []
    for item in values:
        identity = key(item)
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result
