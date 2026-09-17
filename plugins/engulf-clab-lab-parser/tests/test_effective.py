from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engulf_clab_lab_parser import (
    TopologyError,
    TopologySession,
    effective_nodes,
    load_topology,
    topology_declarations,
)


def document():
    return {
        "topology": {
            "defaults": {
                "kind": "linux",
                "env": {"DEFAULT": "yes", "VALUE": "defaults"},
                "image": "default:1",
            },
            "kinds": {
                "linux": {
                    "group": "clients",
                    "env": {"KIND": "yes", "VALUE": "kind"},
                    "image": "kind:1",
                }
            },
            "groups": {
                "clients": {
                    "env": {"GROUP": "yes", "VALUE": "group"},
                    "image": "group:1",
                }
            },
            "nodes": {
                "client": {"env": {"NODE": "yes", "VALUE": "node"}, "image": "node:1"}
            },
        }
    }


def test_precedence_with_winning_and_shadowed_origins():
    source = document()
    before = copy.deepcopy(source)
    (node,) = effective_nodes(source)
    assert node.data["env"] == {
        "DEFAULT": "yes",
        "KIND": "yes",
        "GROUP": "yes",
        "NODE": "yes",
        "VALUE": "node",
    }
    assert node.data["image"] == "node:1"
    assert node.origin("env", "VALUE").path == (
        "topology",
        "nodes",
        "client",
        "env",
        "VALUE",
    )
    assert [origin.level for origin in node.declared_origins("env", "VALUE")] == [
        "defaults",
        "kind",
        "group",
        "node",
    ]
    assert node.origin("kind").level == "defaults"
    assert node.origin("group").level == "kind"
    assert node.origin("absent") is None
    assert source == before


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", ""),
        ("false", "false"),
        (False, "false"),
        (True, "true"),
        (None, ""),
        ("remove", "remove"),
    ],
)
def test_env_overrides_are_values_and_never_removal_markers(value, expected):
    source = document()
    source["topology"]["nodes"]["client"]["env"] = {"VALUE": value}
    (node,) = effective_nodes(source)
    assert node.data["env"]["VALUE"] == expected
    assert node.origin("env", "VALUE").level == "node"


@pytest.mark.parametrize("value", ["", None])
def test_empty_scalar_inherits_and_null_or_empty_env_mapping_does_not_clear(value):
    source = document()
    source["topology"]["nodes"]["client"] = {"image": value, "env": None}
    (node,) = effective_nodes(source)
    assert node.data["image"] == "group:1"
    assert node.origin("image").level == "group"
    assert node.data["env"]["VALUE"] == "group"
    source["topology"]["nodes"]["client"]["env"] = {}
    assert effective_nodes(source)[0].data["env"]["VALUE"] == "group"


def test_native_boolean_false_overrides_true_with_its_origin():
    source = document()
    source["topology"]["defaults"]["enforce-startup-config"] = True
    source["topology"]["nodes"]["client"]["enforce-startup-config"] = False
    (node,) = effective_nodes(source)
    assert node.data["enforce-startup-config"] is False
    assert node.origin("enforce-startup-config").level == "node"


def test_yaml_env_scalar_spelling_and_boolean_alias_are_preserved(tmp_path):
    path = tmp_path / "lab.clab.yml"
    path.write_text(
        """topology:
  defaults:
    env:
      VALUE: &flag false
      SPELLING: yes
      EMPTY: null
  nodes:
    client:
      privileged: *flag
      env: {VALUE: False, ENABLED: true}
""",
        encoding="utf-8",
    )
    source = load_topology(path, {})
    (node,) = effective_nodes(source)
    assert node.data["privileged"] is False
    assert node.data["env"]["VALUE"] == "False"
    assert node.data["env"]["SPELLING"] == "yes"
    assert node.data["env"]["EMPTY"] == ""
    assert node.data["env"]["ENABLED"] == "true"


def test_kind_from_node_group_and_defaults_group_and_group_from_kind():
    source = {
        "topology": {
            "defaults": {"kind": "linux", "group": "default"},
            "kinds": {
                "fortinet_fortigate": {"group": "kind-group", "network-mode": "none"}
            },
            "groups": {
                "default": {"kind": "fortinet_fortigate"},
                "explicit": {"kind": "fortinet_fortigate", "network-mode": "host"},
                "kind-group": {"network-mode": "container:other"},
            },
            "nodes": {"defaulted": {}, "grouped": {"group": "explicit"}},
        }
    }
    defaulted, grouped = effective_nodes(source)
    assert defaulted.data["kind"] == "fortinet_fortigate"
    assert defaulted.origin("kind").path == ("topology", "groups", "default", "kind")
    assert defaulted.data["group"] == "kind-group"
    assert defaulted.data["network-mode"] == "container:other"
    assert grouped.data["kind"] == "fortinet_fortigate"
    assert grouped.data["network-mode"] == "host"


def test_null_node_uses_defaults_group_without_kind_group_override():
    source = {
        "topology": {
            "defaults": {"kind": "linux", "group": "default"},
            "kinds": {"linux": {"group": "kind-group"}},
            "groups": {
                "default": {"network-mode": "host"},
                "kind-group": {"network-mode": "none"},
            },
            "nodes": {"null": None, "empty": {}},
        }
    }
    null, empty = effective_nodes(source)
    assert null.data["group"] == "default"
    assert null.data["network-mode"] == "host"
    assert empty.data["group"] == "kind-group"
    assert empty.data["network-mode"] == "none"


def test_snapshots_are_recursively_immutable_and_independent_of_input():
    source = document()
    (node,) = effective_nodes(source)
    with pytest.raises(FrozenInstanceError):
        node.name = "changed"
    with pytest.raises(TypeError):
        node.data["env"]["VALUE"] = "changed"
    with pytest.raises(TypeError):
        node.origins[("image",)] = None
    source["topology"]["nodes"]["client"]["env"]["VALUE"] = "changed"
    assert node.data["env"]["VALUE"] == "node"


def test_session_resolves_a_fresh_materialized_snapshot():
    session = TopologySession(Path("lab.clab.yml"), document())
    before = session.effective_nodes()[0]
    session.editor("test").modify(
        ("topology", "kinds", "linux", "env", "KIND"), "changed"
    )
    assert session.effective_nodes()[0].data["env"]["KIND"] == "changed"
    assert before.data["env"]["KIND"] == "yes"


def test_deferred_edits_can_populate_null_node_and_env_mappings():
    source = {"topology": {"nodes": {"null-node": None, "null-env": {"env": None}}}}
    session = TopologySession(Path("lab.clab.yml"), source)
    mutation = session.editor("test")
    mutation.modify(("topology", "nodes", "null-node", "env", "VALUE"), "first")
    mutation.add(("topology", "nodes", "null-env", "env", "VALUE"), "second")
    assert [node.data["env"]["VALUE"] for node in session.effective_nodes()] == [
        "first",
        "second",
    ]
    assert source["topology"]["nodes"]["null-node"] is None
    assert source["topology"]["nodes"]["null-env"]["env"] is None


def test_redaction_inventory_includes_unused_kinds_and_groups():
    source = document()
    source["topology"]["kinds"]["unused"] = {"env": {"SITE": "private"}}
    source["topology"]["groups"]["unused"] = {"env": {"SITE": "private"}}
    paths = [
        item.field_origin("env", "SITE").path for item in topology_declarations(source)
    ]
    assert ("topology", "kinds", "unused", "env", "SITE") in paths
    assert ("topology", "groups", "unused", "env", "SITE") in paths


def test_malformed_inherited_env_and_structured_remove_marker_fail():
    source = document()
    source["topology"]["kinds"]["linux"]["env"] = ["bad"]
    with pytest.raises(TopologyError, match=r"kinds.linux.env.*mapping"):
        effective_nodes(source)
    source["topology"]["kinds"]["linux"]["env"] = {"VALUE": {"remove": True}}
    with pytest.raises(TopologyError, match=r"VALUE.*scalar string"):
        effective_nodes(source)


def test_lists_merge_and_whole_object_replacement_drops_old_child_origins():
    source = document()
    source["topology"]["defaults"].update(
        {"exec": ["a", "b"], "dns": {"search": ["local"], "servers": ["192.0.2.1"]}}
    )
    source["topology"]["nodes"]["client"].update(
        {"exec": ["b", "c"], "dns": {"servers": ["192.0.2.2"]}}
    )
    (node,) = effective_nodes(source)
    assert node.data["exec"] == ("a", "b", "c")
    assert node.origin("exec", 1).level == "defaults"
    assert node.origin("exec", 2).path[-1] == 1
    assert node.data["dns"] == {"servers": ("192.0.2.2",)}
    assert node.origin("dns", "search") is None
    assert len(node.declared_origins("dns", "servers")) == 2
