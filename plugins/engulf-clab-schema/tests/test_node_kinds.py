import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from engulf_clab_schema_api import (
    ContainerlabSourceHint,
    ContainerlabSourceKind,
    VrnetlabSourceHint,
)

from engulf_clab_schema.node_kinds import resolve_node_kind_catalog
from engulf_clab_schema.source import BaseSchema, resolve_base_schema


class State:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, name: str) -> Path:
        return self.directory / name


def test_catalog_uses_selected_containerlab_and_vrnetlab_checkouts(tmp_path: Path) -> None:
    containerlab = tmp_path / "custom-containerlab"
    kind_docs = containerlab / "docs" / "manual" / "kinds"
    kind_docs.mkdir(parents=True)
    (kind_docs / "index.md").write_text(
        "| **Custom Router** | [`custom_router`](custom.md) | supported | VM |\n",
        encoding="utf-8",
    )
    (kind_docs / "custom.md").write_text("# Custom Containerlab guidance\n", encoding="utf-8")

    vrnetlab = tmp_path / "custom-vrnetlab"
    (vrnetlab / "common").mkdir(parents=True)
    (vrnetlab / "common" / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")
    builder = vrnetlab / "custom" / "router"
    builder.mkdir(parents=True)
    (builder / "README.md").write_text("# Custom vrnetlab builder\n", encoding="utf-8")

    document = {
        "properties": {},
        "definitions": {
            "node-config": {
                "properties": {"kind": {"type": "string", "enum": ["custom_router"]}}
            }
        },
    }
    content = json.dumps(document).encode()
    base = BaseSchema(
        document,
        content,
        "checkout",
        None,
        None,
        None,
        False,
        hashlib.sha256(content).hexdigest(),
    )
    state = State(tmp_path / "state")
    state.directory.mkdir()

    catalog = resolve_node_kind_catalog(
        state,  # type: ignore[arg-type]
        {"VRNETLAB_DIR": str(vrnetlab)},
        base,
        ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=containerlab),
    )

    assert [item.kind for item in catalog.kinds] == ["custom_router"]
    kind = catalog.kinds[0]
    assert kind.summary == "Custom Router"
    assert kind.containerlab_path == "docs/manual/kinds/custom.md"
    assert kind.containerlab_content == b"# Custom Containerlab guidance\n"
    assert kind.vrnetlab_path == "custom/router/README.md"
    assert kind.vrnetlab_content == b"# Custom vrnetlab builder\n"
    assert catalog.containerlab.kind == "checkout"
    assert catalog.vrnetlab.kind == "checkout"


def test_missing_upstream_documents_do_not_remove_a_valid_kind(tmp_path: Path) -> None:
    containerlab = tmp_path / "containerlab"
    containerlab.mkdir()
    vrnetlab = tmp_path / "vrnetlab"
    (vrnetlab / "common").mkdir(parents=True)
    (vrnetlab / "common" / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")
    document = {
        "properties": {},
        "definitions": {
            "node-config": {"properties": {"kind": {"enum": ["undocumented"]}}}
        },
    }
    content = json.dumps(document).encode()
    base = BaseSchema(
        document,
        content,
        "checkout",
        None,
        None,
        None,
        False,
        hashlib.sha256(content).hexdigest(),
    )
    state = State(tmp_path / "state")
    state.directory.mkdir()

    catalog = resolve_node_kind_catalog(
        state,  # type: ignore[arg-type]
        {"VRNETLAB_DIR": str(vrnetlab)},
        base,
        ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=containerlab),
    )

    assert catalog.kinds[0].kind == "undocumented"
    assert catalog.kinds[0].containerlab_content is None
    assert catalog.kinds[0].vrnetlab_content is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_repository_sources_resolve_exact_commits_and_documents(tmp_path: Path) -> None:
    containerlab = tmp_path / "containerlab-repository"
    schema = containerlab / "schemas" / "clab.schema.json"
    schema.parent.mkdir(parents=True)
    document = {
        "properties": {},
        "definitions": {
            "node-config": {
                "properties": {"kind": {"type": "string", "enum": ["vendor_router"]}}
            }
        },
    }
    schema.write_text(json.dumps(document), encoding="utf-8")
    kind_docs = containerlab / "docs" / "manual" / "kinds"
    kind_docs.mkdir(parents=True)
    (kind_docs / "index.md").write_text(
        "| **Vendor Router** | [`vendor_router`](router.md) | supported | VM |\n",
        encoding="utf-8",
    )
    (kind_docs / "router.md").write_text("# Repository kind\n", encoding="utf-8")
    containerlab_revision = _commit(containerlab)

    vrnetlab = tmp_path / "vrnetlab-repository"
    (vrnetlab / "common").mkdir(parents=True)
    (vrnetlab / "common" / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")
    builder = vrnetlab / "vendor" / "router"
    builder.mkdir(parents=True)
    (builder / "README.md").write_text("# Repository builder\n", encoding="utf-8")
    vrnetlab_revision = _commit(vrnetlab)

    state = State(tmp_path / "state")
    state.directory.mkdir()
    hint = ContainerlabSourceHint(
        ContainerlabSourceKind.REPOSITORY,
        repository=str(containerlab),
        revision="HEAD",
    )
    base = resolve_base_schema(
        state,  # type: ignore[arg-type]
        {},
        hint,
        refresh=True,
    )
    catalog = resolve_node_kind_catalog(
        state,  # type: ignore[arg-type]
        {},
        base,
        hint,
        VrnetlabSourceHint(repository=str(vrnetlab), revision="HEAD"),
        refresh=True,
    )

    assert base.revision == containerlab_revision
    assert catalog.containerlab.revision == containerlab_revision
    assert catalog.vrnetlab.revision == vrnetlab_revision
    assert catalog.kinds[0].containerlab_content == b"# Repository kind\n"
    assert catalog.kinds[0].vrnetlab_content == b"# Repository builder\n"


def _commit(repository: Path) -> str:
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    process = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


def _multi_kind_base(kinds: list[str]) -> BaseSchema:
    document = {
        "properties": {},
        "definitions": {
            "node-config": {
                "properties": {"kind": {"type": "string", "enum": kinds}}
            }
        },
    }
    content = json.dumps(document).encode()
    return BaseSchema(
        document,
        content,
        "checkout",
        None,
        None,
        None,
        False,
        hashlib.sha256(content).hexdigest(),
    )


def test_node_kind_allowlist_restricts_the_catalog(tmp_path: Path) -> None:
    containerlab = tmp_path / "containerlab"
    containerlab.mkdir()
    vrnetlab = tmp_path / "vrnetlab"
    (vrnetlab / "common").mkdir(parents=True)
    (vrnetlab / "common" / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")
    state = State(tmp_path / "state")
    state.directory.mkdir()
    base = _multi_kind_base(["linux", "bridge", "fortinet_fortigate", "arista_ceos"])

    catalog = resolve_node_kind_catalog(
        state,  # type: ignore[arg-type]
        {
            "VRNETLAB_DIR": str(vrnetlab),
            "ECLAB_NODE_KINDS": "linux,bridge,fortinet_fortigate",
        },
        base,
        ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=containerlab),
    )

    assert [item.kind for item in catalog.kinds] == [
        "bridge",
        "fortinet_fortigate",
        "linux",
    ]


def test_node_kind_allowlist_unset_compiles_every_kind(tmp_path: Path) -> None:
    containerlab = tmp_path / "containerlab"
    containerlab.mkdir()
    vrnetlab = tmp_path / "vrnetlab"
    (vrnetlab / "common").mkdir(parents=True)
    (vrnetlab / "common" / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")
    state = State(tmp_path / "state")
    state.directory.mkdir()
    base = _multi_kind_base(["linux", "bridge", "fortinet_fortigate", "arista_ceos"])

    catalog = resolve_node_kind_catalog(
        state,  # type: ignore[arg-type]
        {"VRNETLAB_DIR": str(vrnetlab)},
        base,
        ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=containerlab),
    )

    assert len(catalog.kinds) == 4


def test_node_kind_allowlist_rejects_unknown_kinds(tmp_path: Path) -> None:
    containerlab = tmp_path / "containerlab"
    containerlab.mkdir()
    vrnetlab = tmp_path / "vrnetlab"
    (vrnetlab / "common").mkdir(parents=True)
    (vrnetlab / "common" / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")
    state = State(tmp_path / "state")
    state.directory.mkdir()
    base = _multi_kind_base(["linux", "bridge"])

    with pytest.raises(Exception, match="absent from the base schema.*not_a_kind"):
        resolve_node_kind_catalog(
            state,  # type: ignore[arg-type]
            {"VRNETLAB_DIR": str(vrnetlab), "ECLAB_NODE_KINDS": "linux,not_a_kind"},
            base,
            ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=containerlab),
        )


def test_node_kind_allowlist_rejects_an_empty_selection(tmp_path: Path) -> None:
    containerlab = tmp_path / "containerlab"
    containerlab.mkdir()
    vrnetlab = tmp_path / "vrnetlab"
    (vrnetlab / "common").mkdir(parents=True)
    (vrnetlab / "common" / "vrnetlab.py").write_text("# marker\n", encoding="utf-8")
    state = State(tmp_path / "state")
    state.directory.mkdir()
    base = _multi_kind_base(["linux", "bridge"])

    with pytest.raises(Exception, match="at least one valid node kind"):
        resolve_node_kind_catalog(
            state,  # type: ignore[arg-type]
            {"VRNETLAB_DIR": str(vrnetlab), "ECLAB_NODE_KINDS": ",,"},
            base,
            ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=containerlab),
        )
