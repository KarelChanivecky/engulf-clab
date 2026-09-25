"""Contributor hooks must see their own Engulf namespace, not freeze's."""

from types import SimpleNamespace

from engulf_clab_freeze.command import freeze
from engulf_clab_freeze.defrost import defrost


def test_round_trip_routes_state_to_contributor_namespace(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    topology = source / "lab.clab.yml"
    topology.write_text("topology: {nodes: {}}\n")
    workspace = SimpleNamespace(
        directory=tmp_path / "workspace/plugins/engulf_clab.freeze"
    )
    user = SimpleNamespace(directory=tmp_path / "user/plugins/engulf_clab.freeze")
    observed = []

    class Contributor:
        contributor_id = "engulf_clab.pki"

        def freeze(self, context):
            observed.append((context.workspace_state, context.user_state))
            return {"test": True}

        def defrost(self, context):
            observed.append(context.user_state)

    monkeypatch.setattr("engulf_clab_freeze.command.track_archive", lambda *args: None)
    monkeypatch.setattr(
        "engulf_clab_freeze.command.tracked_archives", lambda *args: frozenset()
    )
    archive = tmp_path / "lab.tar.gz"
    freeze(
        topology,
        archive,
        workspace=workspace,
        user_state=user,
        contributors=(Contributor(),),
        environment={},
    )
    defrost(
        archive,
        tmp_path / "restored",
        contributors=(Contributor(),),
        user_state=user.directory,
        environment={},
        initialize_env=False,
        prepare_runtime=False,
        prompt_licenses=False,
    )
    assert observed == [
        (
            workspace.directory.parent / "engulf_clab.pki",
            user.directory.parent / "engulf_clab.pki",
        ),
        user.directory.parent / "engulf_clab.pki",
    ]
