from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engulf_clab_lab_parser.session import (
    TopologyError,
)
from engulf_clab_lab_parser.session import (
    load_topology as load_parsed_topology,
)
from engulf_clab_lab_parser.session import (
    topology_path_from_args as parsed_topology_path_from_args,
)

from .errors import WanError


def load_topology(
    path: Path, environment: Mapping[str, str] | None = None
) -> dict[str, Any]:
    try:
        return load_parsed_topology(path, environment)
    except TopologyError as error:
        raise WanError(str(error)) from error


def topology_path_from_args(args: tuple[str, ...], cwd: Path | None = None) -> Path:
    try:
        return parsed_topology_path_from_args(args, cwd)
    except TopologyError as error:
        raise WanError(str(error)) from error
