from __future__ import annotations

import json
import tomllib
import unittest
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import MagicMock, patch

from engulf_api import (
    AfterGoalAPI,
    ApplicationMetadata,
    BeforeGoalAPI,
    GoalResult,
    GoalResultStatus,
    Invocation,
    InvocationAPI,
    StateStore,
)
from engulf_clab_lab_registry_api import LabRecord, RegistryCommit
from engulf_clab_schema_api import LifecycleStage
from engulf_executable_wrapper_api import BeforeCallEvent, CallMode

from engulf_clab_reclaim.command import (
    ReclaimError,
    execute,
    parse_options,
    parser,
    plan,
)
from engulf_clab_reclaim.docker import DockerClient, DockerError
from engulf_clab_reclaim.model import Container, LabUse, ReclaimPlan
from engulf_clab_reclaim.plugin import PLUGIN_SCHEMA, ReclaimPlugin


class FakeRegistry:
    def __init__(
        self, records: tuple[LabRecord, ...] = (), *, persistent: bool = True
    ) -> None:
        self.record_values = records
        self.updates: list[tuple[LabRecord, ...]] = []
        self.error: RuntimeError | None = None
        self.persistent = persistent
        self.revision = 0

    def records(self) -> tuple[LabRecord, ...]:
        return self.record_values

    def upsert(self, records: tuple[LabRecord, ...]) -> None:
        if self.error is not None:
            raise self.error
        self.updates.append(records)


def committed(revision: int = 0, records: tuple[LabRecord, ...] = ()) -> RegistryCommit:
    return RegistryCommit(committed=True, revision=revision, records=records)


class MemoryState:
    """Minimal writable user store, shared by the two real plugins."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def exists(self, filename: str) -> bool:
        return filename in self.values

    def read_text(self, filename: str, **_kwargs: object) -> str:
        return self.values[filename]

    def write_text(self, filename: str, data: str, **_kwargs: object) -> None:
        self.values[filename] = data

    @contextmanager
    def transaction(self, **_kwargs: object) -> Iterator[MemoryState]:
        yield self


class SharedAPI:
    """One shared context table plus the plugin-owned store, as the runtime."""

    def __init__(self, table: dict[str, object], store: MemoryState) -> None:
        self._table = table
        self._store = store
        self.logger = MagicMock()
        self.application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="ECLAB",
            vendor="Engulf",
            product="ECLAB",
            version="1",
            short_product_name="eclab",
        )

    def get_context(
        self, context_id: str, default: object | None = None
    ) -> object | None:
        return self._table.get(context_id, default)

    def set_context(self, context_id: str, value: object, **_kwargs: object) -> None:
        self._table[context_id] = value

    def state(self, _scope: object) -> MemoryState:
        return self._store

    def leases(self, _names: object, **_kwargs: object) -> AbstractContextManager[None]:
        return nullcontext()


class FakeDocker:
    def __init__(self) -> None:
        self.container_values: tuple[Container, ...] = ()
        self.references: dict[str, str] = {}
        self.images: dict[str, str] = {}
        self.removed_containers: list[str] = []
        self.removed_images: list[str] = []
        self.container_failures: set[str] = set()
        self.image_failures: set[str] = set()
        self.storage_values = [0, 0]
        self.storage_error: DockerError | None = None

    def containers(self) -> tuple[Container, ...]:
        return self.container_values

    def resolve_images(self, references: tuple[str, ...]) -> dict[str, str]:
        return {
            reference: self.references[reference]
            for reference in references
            if reference in self.references
        }

    def available_images(self) -> dict[str, str]:
        return self.images

    def storage_bytes(self) -> int:
        if self.storage_error is not None:
            raise self.storage_error
        if len(self.storage_values) > 1:
            return self.storage_values.pop(0)
        return self.storage_values[0]

    def remove_container(self, container_id: str) -> None:
        if container_id in self.container_failures:
            raise DockerError(f"cannot remove container {container_id}")
        self.removed_containers.append(container_id)

    def remove_image(self, image_id: str) -> None:
        if image_id in self.image_failures:
            raise DockerError(f"cannot remove image {image_id}")
        self.removed_images.append(image_id)


def topology(root: Path, name: str = "one", image: str = "example:1") -> Path:
    path = root / "lab.clab.yml"
    path.write_text(
        f"name: {name}\ntopology:\n  nodes:\n    node:\n      image: {image}\n",
        encoding="utf-8",
    )
    return path


class PlanningTest(unittest.TestCase):
    def test_single_lab_deletes_unique_and_preserves_shared_images(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected_topology = topology(root)
            records = (
                LabRecord(
                    "one",
                    root,
                    selected_topology,
                    frozenset({"sha256:unique", "sha256:shared", "sha256:historical"}),
                    True,
                ),
                LabRecord(
                    "two",
                    Path("/labs/two"),
                    None,
                    frozenset({"sha256:shared"}),
                    True,
                ),
            )
            docker = FakeDocker()
            docker.container_values = (
                Container("one-unique", "one", selected_topology, "sha256:unique"),
                Container("one-shared", "one", selected_topology, "sha256:shared"),
                Container(
                    "two-shared",
                    "two",
                    Path("/labs/two/lab.clab.yml"),
                    "sha256:shared",
                ),
            )
            docker.images = {
                "unique": "sha256:unique",
                "shared": "sha256:shared",
                "historical": "sha256:historical",
            }

            reclaim_plan = plan(
                (),
                cwd=root,
                environment={},
                registry=FakeRegistry(records),
                docker=docker,
            )

        self.assertEqual(
            reclaim_plan.image_ids,
            ("sha256:historical", "sha256:unique"),
        )
        self.assertEqual(reclaim_plan.container_ids, ("one-unique", "one-shared"))
        self.assertEqual(reclaim_plan.preserved_shared_image_ids, ("sha256:shared",))

    def test_all_deletes_shared_union_when_every_lab_is_destroyed(self) -> None:
        one = Path("/labs/one/lab.clab.yml")
        two = Path("/labs/two/lab.clab.yml")
        records = (
            LabRecord("one", one.parent, one, frozenset({"sha256:shared"}), True),
            LabRecord("two", two.parent, two, frozenset({"sha256:shared"}), True),
        )
        docker = FakeDocker()
        docker.images = {"shared": "sha256:shared"}

        reclaim_plan = plan(
            ("--all",),
            cwd=Path("/labs"),
            environment={},
            registry=FakeRegistry(records),
            docker=docker,
        )

        self.assertEqual(reclaim_plan.container_ids, ())
        self.assertEqual(reclaim_plan.image_ids, ("sha256:shared",))
        self.assertEqual(reclaim_plan.preserved_shared_image_ids, ())

    def test_all_fails_when_any_lab_still_has_a_container(self) -> None:
        lab = Path("/labs/one/lab.clab.yml")
        docker = FakeDocker()
        docker.container_values = (
            Container("container", "one", lab, "sha256:image", False),
        )

        with self.assertRaisesRegex(ReclaimError, "containers remain for: one"):
            plan(
                ("--all",),
                cwd=Path("/labs"),
                environment={},
                registry=FakeRegistry(),
                docker=docker,
            )

    def test_destroy_reclaim_all_can_plan_before_containers_are_destroyed(self) -> None:
        lab = Path("/labs/one/lab.clab.yml")
        other = Path("/labs/two/lab.clab.yml")
        docker = FakeDocker()
        docker.container_values = (
            Container("one-container", "one", lab, "sha256:shared", True),
            Container("two-container", "two", other, "sha256:shared", True),
        )
        docker.images = {"shared": "sha256:shared"}

        reclaim_plan = plan(
            ("--all",),
            cwd=Path("/labs"),
            environment={},
            registry=FakeRegistry(),
            docker=docker,
            allow_deployed_all=True,
        )

        self.assertEqual(
            reclaim_plan.container_ids, ("one-container", "two-container")
        )
        self.assertEqual(reclaim_plan.image_ids, ("sha256:shared",))
        self.assertEqual(reclaim_plan.preserved_shared_image_ids, ())

    def test_all_stopped_selects_only_stopped_labs_and_preserves_shared(self) -> None:
        stopped = Path("/labs/stopped/lab.clab.yml")
        running = Path("/labs/running/lab.clab.yml")
        docker = FakeDocker()
        docker.container_values = (
            Container("stopped", "stopped", stopped, "sha256:shared", False),
            Container("running", "running", running, "sha256:shared", True),
        )
        docker.images = {"shared": "sha256:shared"}

        reclaim_plan = plan(
            ("--all", "--stopped"),
            cwd=Path("/labs"),
            environment={},
            registry=FakeRegistry(),
            docker=docker,
        )

        self.assertEqual(tuple(lab.name for lab in reclaim_plan.labs), ("stopped",))
        self.assertEqual(reclaim_plan.container_ids, ("stopped",))
        self.assertEqual(reclaim_plan.image_ids, ())
        self.assertEqual(reclaim_plan.preserved_shared_image_ids, ("sha256:shared",))

    def test_all_stopped_removes_images_shared_only_inside_selected_labs(self) -> None:
        first = Path("/labs/first/lab.clab.yml")
        second = Path("/labs/second/lab.clab.yml")
        running = Path("/labs/running/lab.clab.yml")
        docker = FakeDocker()
        docker.container_values = (
            Container("first", "first", first, "sha256:selected", False),
            Container("second", "second", second, "sha256:selected", False),
            Container("running", "running", running, "sha256:outside", True),
            Container("first-outside", "first", first, "sha256:outside", False),
        )
        docker.images = {
            "selected": "sha256:selected",
            "outside": "sha256:outside",
        }

        reclaim_plan = plan(
            ("--all", "--stopped"),
            cwd=Path("/labs"),
            environment={},
            registry=FakeRegistry(),
            docker=docker,
        )

        self.assertEqual(reclaim_plan.image_ids, ("sha256:selected",))
        self.assertEqual(reclaim_plan.preserved_shared_image_ids, ("sha256:outside",))

    def test_never_deployed_lab_resolves_topology_image(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            topology(root, image="example/router:1")
            docker = FakeDocker()
            docker.references = {"example/router:1": "sha256:resolved"}
            docker.images = {"resolved": "sha256:resolved"}

            reclaim_plan = plan(
                (),
                cwd=root,
                environment={},
                registry=FakeRegistry(),
                docker=docker,
            )

        self.assertEqual(reclaim_plan.image_ids, ("sha256:resolved",))
        self.assertFalse(reclaim_plan.observations[0].ever_deployed)

    def test_topology_and_all_conflict(self) -> None:
        with self.assertRaises(SystemExit):
            parser("eclab reclaim").parse_args(("-t", "lab.clab.yml", "--all"))

    def test_stopped_requires_all(self) -> None:
        with self.assertRaises(SystemExit):
            parse_options(("--stopped",), "eclab reclaim")


class ExecutionTest(unittest.TestCase):
    def test_deletes_after_a_committed_registry(self) -> None:
        events: list[str] = []

        class Docker(FakeDocker):
            def remove_container(self, container_id: str) -> None:
                events.append(f"container:{container_id}")
                super().remove_container(container_id)

            def remove_image(self, image_id: str) -> None:
                events.append(f"image:{image_id}")
                super().remove_image(image_id)

        record = LabRecord(
            "one", Path("/labs/one"), None, frozenset({"sha256:image"}), True
        )
        reclaim_plan = ReclaimPlan(
            (LabUse("one", record.directory, None, record.image_ids, ("c",), True),),
            ("c",),
            ("sha256:image",),
            (),
            (record,),
        )

        code = execute(
            reclaim_plan,
            commit=committed(records=(record,)),
            docker=Docker(),
            logger=MagicMock(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(events, ["container:c", "image:sha256:image"])

    def test_uncommitted_registry_aborts_with_zero_deletes(self) -> None:
        """durability-000: a failed durable write stops every delete."""
        docker = FakeDocker()
        reclaim_plan = ReclaimPlan((), ("c",), ("sha256:image",), (), ())
        logger = MagicMock()

        code = execute(
            reclaim_plan,
            commit=RegistryCommit(committed=False, revision=0, error="unavailable"),
            docker=docker,
            logger=logger,
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, [])
        self.assertEqual(docker.removed_images, [])
        logger.error.assert_called_once()

    def test_crash_before_delete_leaves_observations_committed(self) -> None:
        """durability-001: the commit precedes any delete request."""
        from engulf_clab_lab_registry.storage import (
            SessionLabRegistry,
            StateLabRegistry,
        )

        record = LabRecord(
            "one", Path("/labs/one"), None, frozenset({"sha256:image"}), False
        )
        store = MemoryState()
        # The owner loads, the visitor records intent, the owner commits: this is
        # exactly the pre-delete half of the chain.
        session = SessionLabRegistry(
            StateLabRegistry(cast(StateStore, store)).records()
        )
        session.upsert((record,))
        StateLabRegistry(cast(StateStore, store)).commit(session)

        # The process dies here, before execute(). A fresh invocation
        # (a new store handle over the same files) still sees the observation.
        fresh = StateLabRegistry(cast(StateStore, store))
        self.assertEqual(fresh.revision(), 1)
        self.assertEqual(fresh.records()[0].image_ids, frozenset({"sha256:image"}))

    def test_deletion_failures_do_not_stop_independent_attempts(self) -> None:
        docker = FakeDocker()
        docker.container_failures = {"bad"}
        reclaim_plan = ReclaimPlan(
            (),
            ("bad", "good"),
            ("sha256:image",),
            (),
            (),
        )

        code = execute(
            reclaim_plan,
            commit=committed(),
            docker=docker,
            logger=MagicMock(),
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, ["good"])
        self.assertEqual(docker.removed_images, ["sha256:image"])

    def test_reports_measured_storage_reclaimed(self) -> None:
        docker = FakeDocker()
        docker.storage_values = [8 * 1024**3, 5 * 1024**3]
        logger = MagicMock()

        code = execute(
            ReclaimPlan((), (), (), (), ()),
            commit=committed(),
            docker=docker,
            logger=logger,
        )

        self.assertEqual(code, 0)
        self.assertEqual(logger.info.call_args.args[-1], "3.00 GiB")

    def test_destroy_reclaim_uses_storage_snapshot_taken_before_destroy(self) -> None:
        docker = FakeDocker()
        docker.storage_bytes = MagicMock(return_value=7)  # type: ignore[method-assign]
        logger = MagicMock()

        code = execute(
            ReclaimPlan((), (), (), (), (), storage_before=10),
            commit=committed(),
            docker=docker,
            logger=logger,
        )

        self.assertEqual(code, 0)
        self.assertEqual(logger.info.call_args.args[-1], "3 B")
        docker.storage_bytes.assert_called_once_with()

    def test_reports_each_resource_reclaimed(self) -> None:
        docker = FakeDocker()
        logger = MagicMock()

        code = execute(
            ReclaimPlan((), ("container",), ("sha256:image",), (), ()),
            commit=committed(),
            docker=docker,
            logger=logger,
        )

        self.assertEqual(code, 0)
        info_calls = [call.args for call in logger.info.call_args_list]
        self.assertIn(("reclaimed container: %s", "container"), info_calls)
        self.assertIn(("reclaimed image: %s", "sha256:image"), info_calls)

    def test_storage_measurement_failure_aborts_before_deletion(self) -> None:
        docker = FakeDocker()
        docker.storage_error = DockerError("unavailable")

        code = execute(
            ReclaimPlan((), ("container",), ("sha256:image",), (), ()),
            commit=committed(),
            docker=docker,
            logger=MagicMock(),
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, [])
        self.assertEqual(docker.removed_images, [])

    def test_final_storage_measurement_failure_reports_unavailable(self) -> None:
        docker = FakeDocker()
        docker.storage_bytes = MagicMock(  # type: ignore[method-assign]
            side_effect=(1024, DockerError("unavailable"))
        )
        logger = MagicMock()

        code = execute(
            ReclaimPlan((), ("container",), (), (), ()),
            commit=committed(),
            docker=docker,
            logger=logger,
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, ["container"])
        self.assertEqual(logger.info.call_args.args[-1], "unavailable")


class RevalidationTest(unittest.TestCase):
    """The revision fence that guards a plan against a concurrent writer."""

    def test_new_identity_owner_preserves_the_image(self) -> None:
        """ownership-new-identity: a newly owning lab keeps its image."""
        target = LabRecord(
            "one", Path("/labs/one"), None, frozenset({"sha256:shared"}), True
        )
        newcomer = LabRecord(
            "two", Path("/labs/two"), None, frozenset({"sha256:shared"}), True
        )
        reclaim_plan = ReclaimPlan(
            (LabUse("one", target.directory, None, target.image_ids, ("c",), True),),
            ("c",),
            ("sha256:shared",),
            (),
            (target,),
            base_revision=3,
        )
        docker = FakeDocker()
        logger = MagicMock()

        code = execute(
            reclaim_plan,
            commit=committed(revision=4, records=(target, newcomer)),
            docker=docker,
            logger=logger,
        )

        self.assertEqual(code, 0)
        self.assertEqual(docker.removed_images, [])
        self.assertEqual(docker.removed_containers, ["c"])

    def test_changed_target_record_aborts_with_zero_deletes(self) -> None:
        """ownership-same-identity: a moved target record invalidates the plan."""
        target = LabRecord(
            "one", Path("/labs/one"), None, frozenset({"sha256:old"}), True
        )
        changed = LabRecord(
            "one", Path("/labs/one"), None, frozenset({"sha256:new"}), True
        )
        reclaim_plan = ReclaimPlan(
            (LabUse("one", target.directory, None, target.image_ids, ("c",), True),),
            ("c",),
            ("sha256:old",),
            (),
            (target,),
            base_revision=3,
        )
        docker = FakeDocker()
        logger = MagicMock()

        code = execute(
            reclaim_plan,
            commit=committed(revision=4, records=(changed,)),
            docker=docker,
            logger=logger,
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, [])
        self.assertEqual(docker.removed_images, [])
        self.assertIn("re-run reclaim", logger.error.call_args.args[1])

    def test_moved_revision_without_inventory_aborts(self) -> None:
        """A fence that moved but carries no records must never delete blind."""
        reclaim_plan = ReclaimPlan(
            (),
            ("c",),
            ("sha256:image",),
            (),
            (),
            base_revision=3,
        )
        docker = FakeDocker()

        code = execute(
            reclaim_plan,
            commit=committed(revision=4),
            docker=docker,
            logger=MagicMock(),
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, [])
        self.assertEqual(docker.removed_images, [])

    def test_unchanged_revision_deletes_the_planned_set(self) -> None:
        reclaim_plan = ReclaimPlan(
            (),
            (),
            ("sha256:image",),
            (),
            (),
            base_revision=7,
        )
        docker = FakeDocker()

        code = execute(
            reclaim_plan,
            commit=committed(revision=7),
            docker=docker,
            logger=MagicMock(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(docker.removed_images, ["sha256:image"])


class DockerTest(unittest.TestCase):
    def test_storage_snapshot_sums_reclaim_owned_categories(self) -> None:
        docker = DockerClient()
        payload = json.dumps(
            [
                {"Type": "Images", "Size": "1.5GB"},
                {"Type": "Containers", "Size": "512MiB"},
                {"Type": "Local Volumes", "Size": "1000B"},
                {"Type": "Build Cache", "Size": "9GB"},
            ]
        )
        with patch.object(docker, "_run", return_value=payload):
            measured = docker.storage_bytes()

        self.assertEqual(measured, 1_500_000_000 + 512 * 1024**2 + 1000)

    def test_container_discovery_reports_running_state(self) -> None:
        docker = DockerClient()
        payload = json.dumps(
            [
                {
                    "Id": "container",
                    "Image": "sha256:image",
                    "State": {"Running": True},
                    "Config": {
                        "Labels": {
                            "containerlab": "demo",
                            "clab-topo-file": "/labs/demo/lab.clab.yml",
                        }
                    },
                }
            ]
        )
        with patch.object(docker, "_run", side_effect=("container\n", payload)):
            containers = docker.containers()

        self.assertTrue(containers[0].running)

    def test_image_removal_is_not_forced(self) -> None:
        docker = DockerClient()
        with patch.object(
            docker,
            "_run",
            side_effect=(json.dumps([{"RepoTags": [], "RepoDigests": []}]), ""),
        ) as run:
            docker.remove_image("sha256:image")
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ("image", "inspect", "sha256:image"),
                ("image", "rm", "sha256:image"),
            ],
        )
        self.assertNotIn("--force", run.call_args_list[-1].args[0])

    def test_image_removal_removes_all_repository_references_without_force(
        self,
    ) -> None:
        docker = DockerClient()
        inspect = json.dumps(
            [
                {
                    "RepoTags": ["example/router:latest", "mirror/router:1"],
                    "RepoDigests": ["example/router@sha256:digest"],
                }
            ]
        )
        with patch.object(docker, "_run", side_effect=(inspect, "")) as run:
            docker.remove_image("sha256:image")

        self.assertEqual(
            run.call_args_list[-1].args[0],
            (
                "image",
                "rm",
                "example/router:latest",
                "mirror/router:1",
                "example/router@sha256:digest",
            ),
        )
        self.assertNotIn("--force", run.call_args_list[-1].args[0])

    def test_already_removed_objects_are_tolerated_on_retry(self) -> None:
        """durability-002: a retry after a mid-delete crash must not fail."""
        docker = DockerClient()
        with patch.object(
            docker,
            "_run",
            side_effect=DockerError(
                "docker container rm failed: Error response from daemon: "
                "No such container: gone"
            ),
        ):
            docker.remove_container("gone")
        with patch.object(
            docker,
            "_run",
            side_effect=DockerError(
                "docker image rm failed: Error response from daemon: "
                "No such image: sha256:gone"
            ),
        ):
            docker.remove_image("sha256:gone")

    def test_genuine_removal_failures_still_raise(self) -> None:
        docker = DockerClient()
        with (
            patch.object(
                docker,
                "_run",
                side_effect=(
                    json.dumps([{"RepoTags": ["example/router:latest"]}]),
                    DockerError(
                        "docker image rm failed: conflict: image is being used"
                    ),
                ),
            ),
            self.assertRaises(DockerError),
        ):
            docker.remove_image("sha256:busy")


class PluginTest(unittest.TestCase):
    def test_package_declares_registry_before_reclaim(self) -> None:
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_reclaim"
        ]
        self.assertEqual(
            group,
            {
                "engulf_clab.lab_registry": "preprocess=before; postprocess=before",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )
        goal = project["entry-points"][
            "engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"
        ]
        application = project["entry-points"][
            "engulf.plugins.v1.application.engulf_clab"
        ]
        self.assertEqual(goal, application)
        self.assertEqual(tuple(goal), ("engulf_clab.reclaim",))

    def test_schema_declares_reclaim_and_destructive_scope(self) -> None:
        application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="ECLAB",
            vendor="Engulf",
            product="ECLAB",
            version="1",
            short_product_name="eclab",
        )
        names = {option.name for option in PLUGIN_SCHEMA.options(application)}
        self.assertTrue(
            {"reclaim", "-t", "--all", "--stopped", "--reclaim"}.issubset(names)
        )
        annotations = {
            annotation.subject: annotation
            for annotation in PLUGIN_SCHEMA.annotations(application)
        }
        self.assertEqual(
            annotations["reclaim"].lifecycle,
            (LifecycleStage.BEFORE_GOAL, LifecycleStage.AFTER_GOAL),
        )
        self.assertIn("are deleted", " ".join(annotations["reclaim"].implies))
        self.assertIn("storage reclaimed", " ".join(annotations["reclaim"].implies))
        self.assertIn(
            "committed to the lab registry before any deletion",
            " ".join(annotations["reclaim"].implies),
        )

    def _before_goal_api(self) -> MagicMock:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "eclab"
        return api

    def test_before_goal_stages_the_plan_without_deleting(self) -> None:
        api = self._before_goal_api()
        invocation = Invocation(("reclaim", "--all"), Path("/labs"), {})
        registry = FakeRegistry()
        reclaim_plan = ReclaimPlan((), (), (), (), (), base_revision=2)

        with (
            patch("engulf_clab_reclaim.plugin.lab_registry", return_value=registry),
            patch("engulf_clab_reclaim.plugin.DockerClient"),
            patch(
                "engulf_clab_reclaim.plugin.plan", return_value=reclaim_plan
            ) as planner,
            patch("engulf_clab_reclaim.plugin.execute") as executor,
        ):
            result = ReclaimPlugin().before_goal(invocation, api)

        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(result.exit_code, 0)
        api.leases.assert_called_once_with(("eclab-reclaim:docker",))
        planner.assert_called_once()
        executor.assert_not_called()
        # The intent the registry owner commits, staged for its own after_goal.
        self.assertEqual(registry.updates, [()])
        contexts = {call.args[0]: call.args[1] for call in api.set_context.call_args_list}
        self.assertIs(contexts["engulf_clab.reclaim.plan"], reclaim_plan)

    def test_destroy_reclaim_stages_before_destroy_and_executes_after(self) -> None:
        api = self._before_goal_api()
        invocation = Invocation(("destroy", "--all", "--reclaim"), Path("/labs"), {})
        registry = FakeRegistry()
        reclaim_plan = ReclaimPlan((), (), (), (), ())

        with (
            patch("engulf_clab_reclaim.plugin.lab_registry", return_value=registry),
            patch("engulf_clab_reclaim.plugin.DockerClient") as docker,
            patch("engulf_clab_reclaim.plugin.plan", return_value=reclaim_plan) as planner,
        ):
            docker.return_value.storage_bytes.return_value = 12 * 1024**3
            result = ReclaimPlugin().before_goal(invocation, api)

        self.assertIsNone(result)
        self.assertTrue(planner.call_args.kwargs["allow_deployed_all"])
        staged = api.set_context.call_args.args[1]
        self.assertIsInstance(staged, ReclaimPlan)
        self.assertEqual(staged.storage_before, 12 * 1024**3)

        after_api = MagicMock(spec=AfterGoalAPI)
        after_api.application = api.application
        after_api.get_context.side_effect = lambda context_id: {
            "engulf_clab.reclaim.plan": staged,
            "engulf_clab.lab_registry.commit": committed(),
        }.get(context_id)
        native_result = GoalResult.completed(value={"destroyed": True})
        with (
            patch("engulf_clab_reclaim.plugin.DockerClient"),
            patch("engulf_clab_reclaim.plugin.execute", return_value=0) as executor,
        ):
            after_result = ReclaimPlugin().after_goal(
                invocation, native_result, after_api
            )

        self.assertIs(after_result, native_result)
        executor.assert_called_once()

    def test_destroy_reclaim_flag_is_removed_from_containerlab_call(self) -> None:
        api = MagicMock(spec=InvocationAPI)
        contribution = ReclaimPlugin().analyze_call(
            BeforeCallEvent(
                "containerlab",
                ("destroy", "--all", "--reclaim"),
                CallMode.NORMAL,
            ),
            api,
        )

        assert contribution is not None
        self.assertEqual(contribution.removals, frozenset({2}))

    def test_destroy_without_reclaim_keeps_native_call(self) -> None:
        api = MagicMock(spec=InvocationAPI)
        contribution = ReclaimPlugin().analyze_call(
            BeforeCallEvent("containerlab", ("destroy", "--all"), CallMode.NORMAL),
            api,
        )

        self.assertIsNone(contribution)

    def test_before_goal_refuses_an_unreadable_registry(self) -> None:
        """durability-003: an unreadable registry stops before planning."""
        api = self._before_goal_api()
        invocation = Invocation(("reclaim", "--all"), Path("/labs"), {})
        registry = FakeRegistry(persistent=False)

        with (
            patch("engulf_clab_reclaim.plugin.lab_registry", return_value=registry),
            patch("engulf_clab_reclaim.plugin.DockerClient"),
            patch("engulf_clab_reclaim.plugin.plan") as planner,
            patch("engulf_clab_reclaim.plugin.execute") as executor,
        ):
            result = ReclaimPlugin().before_goal(invocation, api)

        assert result is not None
        self.assertEqual(result.exit_code, 1)
        planner.assert_not_called()
        executor.assert_not_called()
        api.leases.assert_not_called()
        api.logger.error.assert_called_once()

    def test_after_goal_executes_under_lease_with_the_commit_outcome(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "eclab"
        reclaim_plan = ReclaimPlan((), (), (), (), (), base_revision=2)
        outcome = RegistryCommit(True, 3, ())
        api.get_context.side_effect = lambda context_id: {
            "engulf_clab.reclaim.plan": reclaim_plan,
            "engulf_clab.lab_registry.commit": outcome,
        }.get(context_id)
        invocation = Invocation(("reclaim", "--all"), Path("/labs"), {})

        with (
            patch("engulf_clab_reclaim.plugin.DockerClient") as docker,
            patch("engulf_clab_reclaim.plugin.execute", return_value=0) as executor,
        ):
            result = ReclaimPlugin().after_goal(
                invocation, GoalResult.completed(), api
            )

        self.assertEqual(result.exit_code, 0)
        api.leases.assert_called_once_with(("eclab-reclaim:docker",))
        executor.assert_called_once_with(
            reclaim_plan,
            commit=outcome,
            docker=docker.return_value,
            logger=api.logger,
        )

    def test_after_goal_revises_the_exit_code_when_execution_fails(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "eclab"
        reclaim_plan = ReclaimPlan((), (), (), (), ())
        api.get_context.side_effect = lambda context_id: {
            "engulf_clab.reclaim.plan": reclaim_plan,
            "engulf_clab.lab_registry.commit": RegistryCommit(False, 0, error="no"),
        }.get(context_id)
        invocation = Invocation(("reclaim", "--all"), Path("/labs"), {})

        with (
            patch("engulf_clab_reclaim.plugin.DockerClient"),
            patch("engulf_clab_reclaim.plugin.execute", return_value=1),
        ):
            result = ReclaimPlugin().after_goal(
                invocation, GoalResult.completed(), api
            )

        self.assertEqual(result.exit_code, 1)

    def test_after_goal_passes_through_without_a_staged_plan(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = None
        invocation = Invocation(("deploy",), Path("/labs"), {})

        with patch("engulf_clab_reclaim.plugin.execute") as executor:
            result = ReclaimPlugin().after_goal(
                invocation, GoalResult.completed(), api
            )

        self.assertEqual(result.exit_code, 0)
        executor.assert_not_called()
        api.leases.assert_not_called()

    def test_after_goal_ignores_a_failed_before_goal(self) -> None:
        api = MagicMock(spec=AfterGoalAPI)
        api.get_context.return_value = ReclaimPlan((), (), (), (), ())
        invocation = Invocation(("reclaim", "--all"), Path("/labs"), {})

        with patch("engulf_clab_reclaim.plugin.execute") as executor:
            result = ReclaimPlugin().after_goal(
                invocation, GoalResult.completed(exit_code=1), api
            )

        self.assertEqual(result.exit_code, 1)
        executor.assert_not_called()

    def test_help_exits_before_registry_or_lease(self) -> None:
        api = self._before_goal_api()
        invocation = Invocation(("reclaim", "--help"), Path("/labs"), {})

        with (
            patch("engulf_clab_reclaim.plugin.lab_registry") as registry,
            self.assertRaises(SystemExit) as stopped,
        ):
            ReclaimPlugin().before_goal(invocation, api)

        self.assertEqual(stopped.exception.code, 0)
        registry.assert_not_called()
        api.leases.assert_not_called()


class IntegrationOrderingTest(unittest.TestCase):
    """The full two-callback chain across the real registry and reclaim plugins."""

    def test_a_commit_never_overwrites_b_entry_and_never_deletes_b_image(self) -> None:
        """ownership-same-identity-A-fails: A's stale plan cannot harm B."""
        from engulf_clab_lab_registry.plugin import LabRegistryPlugin
        from engulf_clab_lab_registry.storage import (
            SessionLabRegistry,
            StateLabRegistry,
        )
        from engulf_clab_lab_registry_api import (
            LAB_REGISTRY_COMMIT_CONTEXT,
            LAB_REGISTRY_CONTEXT,
        )

        from engulf_clab_reclaim.plugin import RECLAIM_PLAN_CONTEXT

        store = MemoryState()
        state_api = StateLabRegistry(cast(StateStore, store))
        one = LabRecord(
            "one", Path("/labs/one"), None, frozenset({"sha256:one"}), True
        )
        state_api.upsert((one,))
        base_revision = state_api.revision()

        # A loads the snapshot and plans against it.
        session = SessionLabRegistry(state_api.records(), revision=base_revision)
        session.upsert((one,))
        table: dict[str, object] = {LAB_REGISTRY_CONTEXT: session}
        reclaim_plan = ReclaimPlan(
            (LabUse("one", one.directory, None, one.image_ids, ("one-c",), True),),
            ("one-c",),
            ("sha256:one",),
            (),
            (one,),
            base_revision=base_revision,
        )
        table[RECLAIM_PLAN_CONTEXT] = reclaim_plan

        # B registers a new lab with its own image while A is between phases.
        two = LabRecord("two", Path("/labs/two"), None, frozenset({"sha256:two"}), True)
        state_api.upsert((two,))
        self.assertNotEqual(state_api.revision(), base_revision)

        invocation = Invocation(("reclaim", "--all"), Path("/labs"), {})
        result = GoalResult.completed()
        # Phase order: the registry owner commits first, then reclaim deletes.
        LabRegistryPlugin().after_goal(invocation, result, SharedAPI(table, store))
        docker = FakeDocker()
        with patch("engulf_clab_reclaim.plugin.DockerClient", return_value=docker):
            final = ReclaimPlugin().after_goal(
                invocation, GoalResult.completed(), SharedAPI(table, store)
            )

        self.assertEqual(final.exit_code, 0)
        # A deleted only its own lab's image and container.
        self.assertEqual(docker.removed_images, ["sha256:one"])
        self.assertEqual(docker.removed_containers, ["one-c"])
        # B's entry and B's image were never touched.
        stored = {item.name: item for item in state_api.records()}
        self.assertEqual(set(stored), {"one", "two"})
        self.assertEqual(stored["two"].image_ids, frozenset({"sha256:two"}))
        outcome = table[LAB_REGISTRY_COMMIT_CONTEXT]
        self.assertTrue(cast(RegistryCommit, outcome).committed)


if __name__ == "__main__":
    unittest.main()
