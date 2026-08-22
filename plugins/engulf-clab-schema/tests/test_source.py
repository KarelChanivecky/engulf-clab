import json
from pathlib import Path

from engulf_clab_schema_api import ContainerlabSourceHint, ContainerlabSourceKind

from engulf_clab_schema.source import (
    resolve_base_schema,
    sanitize_repository,
    source_hint_from_environment,
)


class State:
    def __init__(self, directory: Path) -> None:
        self.directory = directory


def test_checkout_working_tree_schema_is_authoritative(tmp_path: Path) -> None:
    checkout = tmp_path / "containerlab"
    schema = checkout / "schemas" / "clab.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text(json.dumps({"type": "object", "title": "working tree", "properties": {}}))

    result = resolve_base_schema(
        State(tmp_path / "state"),  # type: ignore[arg-type]
        {},
        ContainerlabSourceHint(ContainerlabSourceKind.CHECKOUT, checkout=checkout),
    )

    assert result.document["title"] == "working tree"
    assert result.source_kind == "checkout"


def test_source_precedence_and_credential_sanitization(tmp_path: Path) -> None:
    hint = source_hint_from_environment(
        {"CONTAINERLAB_BIN": str(tmp_path / "bin"), "CONTAINERLAB_DIR": str(tmp_path / "checkout")}
    )
    assert hint.kind is ContainerlabSourceKind.BINARY
    assert (
        sanitize_repository("https://name:secret@example.test/repo.git?token=bad#fragment")
        == "https://example.test/repo.git"
    )
