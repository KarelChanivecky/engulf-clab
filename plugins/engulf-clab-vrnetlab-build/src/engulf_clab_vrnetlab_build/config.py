from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engulf_clab_ensure_vrnetlab import (
    LABEL_PREFIX,
    LEGACY_VRNETLAB_IMAGE_PATH_ENV,
    VRNETLAB_IMAGE_PATH_ENV,
    VRNETLAB_TYPE_ENV,
    vrnetlab_image_path_env,
    vrnetlab_type_env,
)

from .errors import VrnetlabError
from .topology import TopologyNode, topology_name, topology_nodes

VRNETLAB_TYPE = VRNETLAB_TYPE_ENV
VRNETLAB_IMAGE_PATH = VRNETLAB_IMAGE_PATH_ENV
VRNETLAB_IMAGE_PATH_COMPAT = "ECLAB_VM_IMG"
VRNETLAB_IMAGE_PATH_LEGACY = "ECLAB_VM_SRC"
DEFAULT_VRNETLAB_BUILD_JOBS = 2

_IMAGE_EXPRESSION = re.compile(r"^\$\{([^}:]+)(?:(:?[-=])(.*))?\}$")
_VARIABLE_REFERENCE = re.compile(r"^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})$")
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True)
class BuildRequest:
    node_name: str
    image: str
    builder_type: str
    source: Path | None


def vrnetlab_build_jobs(environ: Mapping[str, str] | None = None) -> int:
    variable = f"{LABEL_PREFIX}_VRNETLAB_BUILD_JOBS"
    value = (os.environ if environ is None else environ).get(variable)
    if value is None:
        return DEFAULT_VRNETLAB_BUILD_JOBS
    try:
        jobs = int(value)
    except ValueError as error:
        raise VrnetlabError(f"{variable} must be a positive integer") from error
    if jobs < 1:
        raise VrnetlabError(f"{variable} must be a positive integer")
    return jobs


def resolve_image_expression(value: str, environ: Mapping[str, str]) -> str:
    match = _IMAGE_EXPRESSION.match(value)
    if match is None:
        if value.startswith("${") or "${" in value:
            raise VrnetlabError(f"unsupported image expression: {value}")
        return value

    name, operator, default = match.groups()
    env_value = environ.get(name)

    if operator is None:
        if env_value is None:
            raise VrnetlabError(
                f"environment variable {name} is required by image expression {value}"
            )
        return env_value

    if operator in (":=", ":-"):
        return env_value if env_value else (default or "")

    raise VrnetlabError(f"unsupported image expression operator {operator} in {value}")


def normalize_env_component(value: str) -> str:
    normalized = _NON_ALPHANUMERIC.sub("_", value.upper()).strip("_")
    if not normalized:
        raise VrnetlabError(f"cannot form an environment variable component from {value!r}")
    return normalized


def scoped_variable_names(lab_name: str, node_name: str, variable: str) -> tuple[str, ...]:
    lab = normalize_env_component(lab_name)
    node = normalize_env_component(node_name)
    name = normalize_env_component(variable)
    candidates = (f"{lab}_{node}_{name}", f"{lab}_{name}", name)
    return tuple(dict.fromkeys(candidates))


def resolve_source_value(
    value: str,
    *,
    lab_name: str,
    node_name: str,
    topology_dir: Path,
    environ: Mapping[str, str],
) -> Path:
    match = _VARIABLE_REFERENCE.match(value)
    if match is not None:
        variable = match.group(1) or match.group(2)
        assert variable is not None
        names = scoped_variable_names(lab_name, node_name, variable)
        resolved_value = next((environ[name] for name in names if environ.get(name)), None)
        if resolved_value is None:
            raise VrnetlabError(
                f"node {node_name} image source references ${variable}, but none of "
                f"these variables are set: {', '.join(names)}"
            )
        value = resolved_value

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = topology_dir / path
    return path.resolve()


def _node_environment(
    node_name: str, node_data: Mapping[str, Any]
) -> Mapping[str, Any]:
    env = node_data.get("env")
    if env is None:
        return {}
    if not isinstance(env, Mapping):
        raise VrnetlabError(f"node {node_name} env must be a YAML mapping")
    return env


def _optional_string(mapping: Mapping[str, Any], key: str, *, owner: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise VrnetlabError(f"{owner} {key} must be a string")
    value = value.strip()
    return value or None


def _source_setting(
    node_env: Mapping[str, Any],
    environ: Mapping[str, str],
    *,
    node_name: str,
    image_path_environment: str,
    image_selectors: Mapping[str, str],
) -> str | None:
    node_selector = image_selectors.get(node_name)
    if node_selector is not None:
        return node_selector
    node_value = _optional_string(node_env, image_path_environment, owner="node environment")
    if node_value is not None:
        return node_value
    default_selector = image_selectors.get("default")
    if default_selector is not None:
        return default_selector
    if value := environ.get(image_path_environment):
        return value
    return (
        environ.get(LEGACY_VRNETLAB_IMAGE_PATH_ENV)
        or environ.get(VRNETLAB_IMAGE_PATH_COMPAT)
        or environ.get(VRNETLAB_IMAGE_PATH_LEGACY)
    )


def build_requests_from_topology(
    topology_path: Path,
    topology_data: dict[str, Any],
    environ: Mapping[str, str] | None = None,
    *,
    image_selectors: Mapping[str, str] | None = None,
) -> list[BuildRequest]:
    current_env = environ if environ is not None else os.environ
    selectors = {} if image_selectors is None else dict(image_selectors)
    if any(
        not isinstance(target, str)
        or not target
        or not isinstance(source, str)
        or not source.strip()
        for target, source in selectors.items()
    ):
        raise VrnetlabError("vrnetlab image selectors must map nonempty node names to sources")
    type_environment = vrnetlab_type_env()
    image_path_environment = vrnetlab_image_path_env()
    requests: list[BuildRequest] = []
    lab_name: str | None = None
    nodes = topology_nodes(topology_data)
    configured_nodes: list[tuple[TopologyNode, Mapping[str, Any], str]] = []

    for node in nodes:
        node_env = _node_environment(node.name, node.data)
        builder_type = _optional_string(node_env, type_environment, owner=f"node {node.name}")
        if builder_type is None:
            continue
        configured_nodes.append((node, node_env, builder_type))

    configured_names = {node.name for node, _environment, _builder in configured_nodes}
    declared_names = {node.name for node in nodes}
    for target in selectors:
        if target == "default":
            continue
        if target not in declared_names:
            raise VrnetlabError(f"vrnetlab image selector {target!r} is not a topology node")
        if target not in configured_names:
            raise VrnetlabError(
                f"vrnetlab image selector {target!r} targets a node without {type_environment}"
            )

    for node, node_env, builder_type in configured_nodes:
        if lab_name is None:
            lab_name = topology_name(topology_data)

        image_value = node.data.get("image")
        if not isinstance(image_value, str) or not image_value.strip():
            raise VrnetlabError(f"vrnetlab node {node.name} is missing image")
        image = resolve_image_expression(image_value.strip(), current_env)
        if not image:
            raise VrnetlabError(f"vrnetlab node {node.name} resolved to an empty image")

        source_value = _source_setting(
            node_env,
            current_env,
            node_name=node.name,
            image_path_environment=image_path_environment,
            image_selectors=selectors,
        )
        source = None
        if source_value is not None:
            source = resolve_source_value(
                source_value,
                lab_name=lab_name,
                node_name=node.name,
                topology_dir=topology_path.resolve().parent,
                environ=current_env,
            )

        requests.append(
            BuildRequest(
                node_name=node.name,
                image=image,
                builder_type=builder_type,
                source=source,
            )
        )

    return requests
