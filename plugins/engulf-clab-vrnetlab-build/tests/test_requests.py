from __future__ import annotations

import pytest

from engulf_clab_vrnetlab_build.errors import VrnetlabError
from engulf_clab_vrnetlab_build.node_kinds import load_node_kind_map
from engulf_clab_vrnetlab_build.requests import build_requests_from_topology


def topology(kind: str | None, builder_type: str) -> dict[str, object]:
    node: dict[str, object] = {
        "image": "vrnetlab/example:1",
        "env": {"ECLAB_VRNETLAB_TYPE": builder_type},
    }
    if kind is not None:
        node["kind"] = kind
    return {"topology": {"nodes": {"router": node}}}


def test_node_kind_mapping_loads_packaged_json() -> None:
    assert load_node_kind_map()["fortinet/fortigate"] == "fortinet_fortigate"


@pytest.mark.parametrize(
    ("builder_type", "kind"),
    [
        ("fortinet/fortigate", "fortinet_fortigate"),
        ("vendor/router", "generic_vm"),
    ],
)
def test_build_requests_accept_expected_kind(builder_type: str, kind: str) -> None:
    requests = build_requests_from_topology(topology(kind, builder_type), {}, None)

    assert requests[0].builder_type == builder_type


@pytest.mark.parametrize(
    ("builder_type", "kind", "expected"),
    [
        ("fortinet/fortigate", "generic_vm", "fortinet_fortigate"),
        ("vendor/router", "linux", "generic_vm"),
        ("vendor/router", None, "generic_vm"),
    ],
)
def test_build_requests_reject_wrong_or_missing_kind(
    builder_type: str, kind: str | None, expected: str
) -> None:
    with pytest.raises(VrnetlabError, match=f"requires kind: {expected}"):
        build_requests_from_topology(topology(kind, builder_type), {}, None)
