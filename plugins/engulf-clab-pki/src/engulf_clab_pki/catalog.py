from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]

Scope = Literal["global", "local"]
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_NAMED_SECTIONS = ("profiles", "stores", "authorities", "certificates")


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EffectiveCatalog:
    defaults: dict[str, Any]
    profiles: dict[str, dict[str, Any]]
    stores: dict[str, dict[str, Any]]
    authorities: dict[str, dict[str, Any]]
    certificates: dict[str, dict[str, Any]]
    nodes: dict[str, dict[str, Any]]
    services: dict[str, dict[str, Any]]
    origins: dict[str, dict[str, Scope]]
    global_catalog: dict[str, Any]
    local_catalog: dict[str, Any]
    warnings: tuple[str, ...]

    def origin(self, section: str, name: str) -> Scope:
        return self.origins[section][name]

    def resolve(
        self, section: str, reference: str, *, owner: Scope = "local"
    ) -> tuple[Scope, str, dict[str, Any]]:
        parts = reference.split("/")
        requested: Scope | None = None
        if parts[0] in {"global", "local"}:
            requested = parts.pop(0)  # type: ignore[assignment]
        if len(parts) != 1 or not parts[0]:
            raise CatalogError(f"invalid {section} reference: {reference!r}")
        name = parts[0]
        if owner == "global" and requested == "local":
            raise CatalogError(f"global {section} reference cannot depend on local/{name}")
        if requested is not None:
            source = self.global_catalog if requested == "global" else self.local_catalog
            value = source.get(section, {}).get(name)
            if not isinstance(value, dict):
                raise CatalogError(f"unknown {requested}/{name} {section[:-1]}")
            return requested, name, copy.deepcopy(value)
        if owner == "global":
            value = self.global_catalog.get(section, {}).get(name)
            if not isinstance(value, dict):
                raise CatalogError(f"unknown global {section[:-1]} {name!r}")
            return "global", name, copy.deepcopy(value)
        value = self.local_catalog.get(section, {}).get(name)
        if isinstance(value, dict):
            return "local", name, copy.deepcopy(value)
        value = self.global_catalog.get(section, {}).get(name)
        if isinstance(value, dict):
            return "global", name, copy.deepcopy(value)
        raise CatalogError(f"unknown {section[:-1]} {name!r}")

    def resolve_authority(
        self, reference: str, *, owner: Scope = "local"
    ) -> tuple[Scope, str, str, dict[str, Any]]:
        parts = reference.split("/")
        requested: Scope | None = None
        if parts and parts[0] in {"global", "local"}:
            requested = parts.pop(0)  # type: ignore[assignment]
        if len(parts) not in {1, 2} or not all(parts):
            raise CatalogError(f"invalid authority reference: {reference!r}")
        authority = parts[0]
        variant = parts[1] if len(parts) == 2 else "default"
        prefix = f"{requested}/" if requested else ""
        scope, name, spec = self.resolve("authorities", prefix + authority, owner=owner)
        variants = spec.get("variants", {})
        if variant != "default" and (not isinstance(variants, dict) or variant not in variants):
            raise CatalogError(f"authority {prefix}{authority!s} has no variant {variant!r}")
        return scope, name, variant, spec

    def public_graph(self) -> dict[str, Any]:
        return _redact(
            {
                "version": 2,
                "defaults": copy.deepcopy(self.defaults),
                **{
                    section: {
                        name: {
                            "origin": self.origins[section][name],
                            "definition": copy.deepcopy(value),
                        }
                        for name, value in values.items()
                    }
                    for section, values in (
                        ("profiles", self.profiles),
                        ("stores", self.stores),
                        ("authorities", self.authorities),
                        ("certificates", self.certificates),
                    )
                },
                "nodes": copy.deepcopy(self.nodes),
                "services": copy.deepcopy(self.services),
                "warnings": list(self.warnings),
            }
        )


def load_catalog(
    path: Path, *, required: bool = False, global_scope: bool = False
) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise CatalogError(f"PKI manifest does not exist: {path}")
        return {"version": 2}
    if path.is_symlink() or not path.is_file():
        raise CatalogError(f"PKI catalog is not a regular file: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CatalogError(f"could not parse PKI catalog {path}: {error}") from error
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise CatalogError(f"PKI catalog must contain a YAML mapping: {path}")
    version = value.get("version")
    if version == 1 or version is None:
        raise CatalogError(
            f"PKI catalog version 1 is no longer supported in {path}; migrate node "
            "certificate requests to ECLAB_PKI_CERTIFICATES and declare version: 2"
        )
    if version != 2:
        raise CatalogError(f"unsupported PKI catalog version in {path}: {version!r}")
    result = copy.deepcopy(value)
    result["version"] = 2
    allowed = {
        "version",
        "defaults",
        "profiles",
        "stores",
        "authorities",
        "certificates",
        "services",
        "unresolved_bindings",
    }
    unknown = sorted(set(result) - allowed)
    if unknown:
        raise CatalogError(f"unknown PKI catalog keys: {', '.join(unknown)}")
    if "nodes" in result:
        raise CatalogError(
            "PKI catalog nodes are a version 1 construct; use topology node "
            "ECLAB_PKI_CERTIFICATES and ECLAB_PKI_PRIVATE_AUTHORITIES lists"
        )
    if global_scope and "services" in result:
        raise CatalogError("global PKI catalogs cannot declare services")
    for section in ("defaults", *_NAMED_SECTIONS, "services"):
        item = result.get(section, {})
        if not isinstance(item, dict):
            raise CatalogError(f"PKI {section} must be a mapping")
        if section != "defaults":
            for name, definition in item.items():
                if not isinstance(name, str) or _ID.fullmatch(name) is None:
                    raise CatalogError(f"invalid PKI {section} name: {name!r}")
                if not isinstance(definition, dict):
                    raise CatalogError(f"PKI {section}.{name} must be a mapping")
    return result


def merge_catalogs(
    global_catalog: dict[str, Any], local_catalog: dict[str, Any]
) -> EffectiveCatalog:
    unresolved = local_catalog.get("unresolved_bindings")
    if unresolved:
        names = (
            ", ".join(sorted(str(value) for value in unresolved))
            if isinstance(unresolved, dict)
            else str(unresolved)
        )
        raise CatalogError(
            f"unresolved frozen PKI bindings: {names}; run defrost with --pki-authority BINDING=REF"
        )
    warnings: list[str] = []
    origins: dict[str, dict[str, Scope]] = {}
    merged: dict[str, dict[str, Any]] = {}
    for section in _NAMED_SECTIONS:
        global_values = copy.deepcopy(global_catalog.get(section, {}))
        local_values = copy.deepcopy(local_catalog.get(section, {}))
        for name in sorted(set(global_values) & set(local_values)):
            warnings.append(f"local {section[:-1]} {name!r} shadows the global definition")
        merged[section] = {**global_values, **local_values}
        origins[section] = {
            name: ("local" if name in local_values else "global") for name in merged[section]
        }
    defaults = _overlay(global_catalog.get("defaults", {}), local_catalog.get("defaults", {}))
    effective = EffectiveCatalog(
        defaults=defaults,
        profiles=merged["profiles"],
        stores=merged["stores"],
        authorities=merged["authorities"],
        certificates=merged["certificates"],
        nodes={},
        services=copy.deepcopy(local_catalog.get("services", {})),
        origins=origins,
        global_catalog=copy.deepcopy(global_catalog),
        local_catalog=copy.deepcopy(local_catalog),
        warnings=tuple(warnings),
    )
    validate_references(effective)
    return effective


def _overlay(base: Any, override: Any) -> dict[str, Any]:
    if not isinstance(base, dict) or not isinstance(override, dict):
        raise CatalogError("PKI defaults must be mappings")
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _overlay(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_references(catalog: EffectiveCatalog) -> None:
    graph: dict[tuple[Scope, str, str], tuple[Scope, str, str] | None] = {}
    for scope_value, source in (
        ("global", catalog.global_catalog),
        ("local", catalog.local_catalog),
    ):
        scope = cast(Scope, scope_value)
        for name, spec in source.get("authorities", {}).items():
            variants: dict[str, dict[str, Any]] = {"default": {}}
            declared = spec.get("variants", {})
            if declared:
                if not isinstance(declared, dict):
                    raise CatalogError(f"authority {scope}/{name} variants must be a mapping")
                variants.update(declared)
            for variant, variant_spec in variants.items():
                if not isinstance(variant_spec, dict):
                    raise CatalogError(f"authority {scope}/{name}/{variant} must be a mapping")
                issuer = variant_spec.get("issuer", spec.get("issuer"))
                graph_node = (scope, str(name), variant)
                if issuer is None:
                    graph[graph_node] = None
                elif not isinstance(issuer, str):
                    raise CatalogError(f"issuer for {scope}/{name}/{variant} must be a string")
                else:
                    target_scope, target_name, target_variant, _ = catalog.resolve_authority(
                        issuer, owner=scope
                    )
                    graph[graph_node] = (target_scope, target_name, target_variant)
    visiting: set[tuple[Scope, str, str]] = set()
    visited: set[tuple[Scope, str, str]] = set()

    def walk(node: tuple[Scope, str, str]) -> None:
        if node in visiting:
            raise CatalogError(
                "authority issuer cycle: " + " -> ".join("/".join(x) for x in (*visiting, node))
            )
        if node in visited:
            return
        visiting.add(node)
        target = graph.get(node)
        if target is not None:
            walk(target)
        visiting.remove(node)
        visited.add(node)

    for graph_node in graph:
        walk(graph_node)
    for scope_value, source in (("global", catalog.global_catalog), ("local", catalog.local_catalog)):
        scope = cast(Scope, scope_value)
        for name, spec in source.get("certificates", {}).items():
            issuer = spec.get("issuer")
            if not isinstance(issuer, str):
                raise CatalogError(f"certificate {scope}/{name} requires issuer")
            catalog.resolve_authority(issuer, owner=scope)
            profile = spec.get("profile")
            if profile is not None:
                if not isinstance(profile, str):
                    raise CatalogError(f"certificate {scope}/{name} profile must be a string")
                if profile != "tls-peer":
                    catalog.resolve("profiles", profile, owner=scope)


def bind_topology_requests(catalog: EffectiveCatalog, topology: dict[str, Any]) -> None:
    """Resolve v2 topology PKI lists and attach immutable declaration copies per node."""
    block = topology.get("topology", {})
    defaults = block.get("defaults", {}) if isinstance(block, dict) else {}
    nodes = block.get("nodes", {}) if isinstance(block, dict) else {}
    if not isinstance(nodes, dict):
        raise CatalogError("topology.nodes must be a mapping")
    default_env = _environment(defaults, "topology defaults")
    bound: dict[str, dict[str, Any]] = {}
    for raw_name, raw_node in nodes.items():
        node_name = str(raw_name)
        if not isinstance(raw_node, dict):
            raise CatalogError(f"topology node {node_name!r} must be a mapping")
        node_env = _environment(raw_node, f"topology node {node_name!r}")
        certificate_refs = _selected_list(
            node_env, default_env, "ECLAB_PKI_CERTIFICATES", node_name
        )
        authority_refs = _selected_list(
            node_env, default_env, "ECLAB_PKI_PRIVATE_AUTHORITIES", node_name
        )
        trust_mode = node_env.get(
            "ECLAB_PKI_TRUST_MODE", default_env.get("ECLAB_PKI_TRUST_MODE", "all")
        )
        if trust_mode not in {"all", "none"}:
            raise CatalogError(f"node {node_name!r} ECLAB_PKI_TRUST_MODE must be all or none")
        trust_include = _selected_list(
            node_env, default_env, "ECLAB_PKI_TRUST_INCLUDE", node_name
        )
        trust_exclude = _selected_list(
            node_env, default_env, "ECLAB_PKI_TRUST_EXCLUDE", node_name
        )
        certificates: list[dict[str, Any]] = []
        seen_certificates: set[str] = set()
        for reference in certificate_refs:
            scope, name, spec = catalog.resolve("certificates", reference)
            canonical = f"{scope}/{name}"
            if canonical in seen_certificates:
                raise CatalogError(
                    f"node {node_name!r} repeats certificate {canonical!r} after resolution"
                )
            seen_certificates.add(canonical)
            declaration = copy.deepcopy(spec)
            declaration.update({"name": canonical, "scope": scope, "declaration_name": name})
            certificates.append(declaration)
        authorities: list[dict[str, Any]] = []
        seen_authorities: set[tuple[str, str, str]] = set()
        for reference in authority_refs:
            scope, name, variant, _spec = catalog.resolve_authority(reference)
            key = (scope, name, variant)
            if key in seen_authorities:
                canonical = "/".join(key[:2]) + (f"/{variant}" if variant != "default" else "")
                raise CatalogError(
                    f"node {node_name!r} repeats private authority {canonical!r} after resolution"
                )
            seen_authorities.add(key)
            canonical = f"{scope}/{name}" + (f"/{variant}" if variant != "default" else "")
            authorities.append({"name": canonical, "private": True})
        trusted: dict[tuple[str, str, str], str] = {}
        if trust_mode == "all":
            for name, spec in catalog.authorities.items():
                scope = catalog.origins["authorities"][name]
                variants = ("default", *spec.get("variants", {}))
                for variant in variants:
                    variant_spec = (
                        spec.get("variants", {}).get(variant, {})
                        if variant != "default"
                        else {}
                    )
                    if variant_spec.get("issuer", spec.get("issuer")) is None:
                        trusted[(scope, name, variant)] = f"{scope}/{name}" + (
                            f"/{variant}" if variant != "default" else ""
                        )
        include_keys: set[tuple[str, str, str]] = set()
        for reference in trust_include:
            scope, name, variant, _spec = catalog.resolve_authority(reference)
            if (scope, name, variant) in include_keys:
                raise CatalogError(
                    f"node {node_name!r} repeats trust include {scope}/{name} after resolution"
                )
            include_keys.add((scope, name, variant))
            trusted[(scope, name, variant)] = (
                f"{scope}/{name}" + (f"/{variant}" if variant != "default" else "")
            )
        exclude_keys: set[tuple[str, str, str]] = set()
        for reference in trust_exclude:
            scope, name, variant, _spec = catalog.resolve_authority(reference)
            if (scope, name, variant) in exclude_keys:
                raise CatalogError(
                    f"node {node_name!r} repeats trust exclude {scope}/{name} after resolution"
                )
            exclude_keys.add((scope, name, variant))
            trusted.pop((scope, name, variant), None)
        bound[node_name] = {
            "certificates": certificates,
            "authorities": authorities,
            "trusted_authorities": [trusted[key] for key in sorted(trusted)],
        }
    catalog.nodes.clear()
    catalog.nodes.update(bound)


def _environment(value: Any, owner: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CatalogError(f"{owner} must be a mapping")
    environment = value.get("env", {})
    if environment is None:
        return {}
    if not isinstance(environment, dict):
        raise CatalogError(f"{owner} env must be a mapping")
    return environment


def _selected_list(
    node: dict[str, Any], defaults: dict[str, Any], variable: str, node_name: str
) -> tuple[str, ...]:
    value = node[variable] if variable in node else defaults.get(variable)
    if value is None:
        return ()
    if not isinstance(value, str):
        raise CatalogError(f"node {node_name!r} {variable} must be a comma-separated string")
    if not value.strip():
        return ()
    parts = tuple(part.strip() for part in value.split(","))
    if any(not part for part in parts):
        raise CatalogError(f"node {node_name!r} {variable} contains an empty reference")
    return parts


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
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
                result[key] = "<redacted>"
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
