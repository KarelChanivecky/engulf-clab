from __future__ import annotations

import tomllib
from pathlib import Path

from engulf_clab_port_check.plugin import _parse_port

PACKAGE = Path(__file__).parents[1]


def test_topology_plugin_order_is_declared_in_packaging() -> None:
    project = tomllib.loads((PACKAGE / "pyproject.toml").read_text())
    edges = project["project"]["entry-points"][
        "engulf.plugins.v1.dependency.engulf_clab_port_check"
    ]

    assert edges["engulf_clab.lab_parser"] == "preprocess=after; postprocess=none"
    assert edges["engulf_clab.lab_writer"] == "preprocess=after; postprocess=none"
    assert edges["engulf_clab.schema"] == "preprocess=after; postprocess=none"


def test_containerlab_port_spellings_keep_protocol_specificity() -> None:
    assert _parse_port("80:8080") == (80, 8080, "tcp", "")
    assert _parse_port("55555:43555/udp") == (55555, 43555, "udp", "/udp")
    assert _parse_port("55554:43554/tcp") == (55554, 43554, "tcp", "/tcp")
    assert _parse_port("65536:80") is None
    assert _parse_port("dynamic:80") is None
