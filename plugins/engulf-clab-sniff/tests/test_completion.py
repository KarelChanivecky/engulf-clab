from __future__ import annotations

from engulf_clab_sniff.completion import _peer_candidates
from engulf_clab_sniff.topology import linked_interface_pairs


def test_peer_completion_shows_interfaces_on_both_link_endpoints() -> None:
    topology = {
        "topology": {
            "nodes": {"fpx": {}, "clbr": {}},
            "links": [
                {"endpoints": ["fpx:port3", "clbr:eth2"]},
                {"endpoints": ["fpx:port4", "clbr:eth3"]},
            ],
        }
    }

    assert linked_interface_pairs(topology, "fpx", "clbr") == (
        ("port3", "eth2"),
        ("port4", "eth3"),
    )
    candidates = _peer_candidates(topology, "fpx", ("clbr",), "cl")

    assert len(candidates) == 1
    assert candidates[0].value == "clbr"
    assert candidates[0].description == (
        "fpx:port3 ↔ clbr:eth2; fpx:port4 ↔ clbr:eth3"
    )
