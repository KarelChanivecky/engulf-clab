from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from engulf_api import ApplicationMetadata, BeforeGoalAPI, GoalResultStatus, Invocation
from engulf_clab_lab_registry_api import LabRecord, LabRegistryError
from engulf_clab_schema_api import LifecycleStage

from engulf_clab_sleep.command import SleepError, execute, parse_options, parser, plan
from engulf_clab_sleep.docker import DockerClient, DockerError
from engulf_clab_sleep.model import Container, LabUse, SleepPlan
from engulf_clab_sleep.plugin import PLUGIN_SCHEMA, SleepPlugin


class FakeRegistry:
    def __init__(self, records: tuple[LabRecord, ...] = ()) -> None:
        self.record_values = records
        self.updates: list[tuple[LabRecord, ...]] = []
        self.error: RuntimeError | None = None

    def records(self) -> tuple[LabRecord, ...]:
        return self.record_values

    def upsert(self, records: tuple[LabRecord, ...]) -> None:
        if self.error is not None:
            raise self.error
        self.updates.append(records)


class FakeDocker:
    def __init__(self) -> None:
        self.container_values: tuple[Container, ...] = ()
        self.references: dict[str, str] = {}
        self.images: dict[str, str] = {}
        self.removed_containers: list[str] = []
        self.removed_images: list[str] = []
        self.container_failures: set[str] = set()
        self.image_failures: set[str] = set()

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

            sleep_plan = plan(
                (),
                cwd=root,
                environment={},
                registry=FakeRegistry(records),
                docker=docker,
            )

        self.assertEqual(
            sleep_plan.image_ids,
            ("sha256:historical", "sha256:unique"),
        )
        self.assertEqual(sleep_plan.container_ids, ("one-unique", "one-shared"))
        self.assertEqual(sleep_plan.preserved_shared_image_ids, ("sha256:shared",))

    def test_all_deletes_shared_union_when_every_lab_is_destroyed(self) -> None:
        one = Path("/labs/one/lab.clab.yml")
        two = Path("/labs/two/lab.clab.yml")
        records = (
            LabRecord("one", one.parent, one, frozenset({"sha256:shared"}), True),
            LabRecord("two", two.parent, two, frozenset({"sha256:shared"}), True),
        )
        docker = FakeDocker()
        docker.images = {"shared": "sha256:shared"}

        sleep_plan = plan(
            ("--all",),
            cwd=Path("/labs"),
            environment={},
            registry=FakeRegistry(records),
            docker=docker,
        )

        self.assertEqual(sleep_plan.container_ids, ())
        self.assertEqual(sleep_plan.image_ids, ("sha256:shared",))
        self.assertEqual(sleep_plan.preserved_shared_image_ids, ())

    def test_all_fails_when_any_lab_still_has_a_container(self) -> None:
        lab = Path("/labs/one/lab.clab.yml")
        docker = FakeDocker()
        docker.container_values = (
            Container("container", "one", lab, "sha256:image", False),
        )

        with self.assertRaisesRegex(SleepError, "containers remain for: one"):
            plan(
                ("--all",),
                cwd=Path("/labs"),
                environment={},
                registry=FakeRegistry(),
                docker=docker,
            )

    def test_all_stopped_selects_only_stopped_labs_and_preserves_shared(self) -> None:
        stopped = Path("/labs/stopped/lab.clab.yml")
        running = Path("/labs/running/lab.clab.yml")
        docker = FakeDocker()
        docker.container_values = (
            Container("stopped", "stopped", stopped, "sha256:shared", False),
            Container("running", "running", running, "sha256:shared", True),
        )
        docker.images = {"shared": "sha256:shared"}

        sleep_plan = plan(
            ("--all", "--stopped"),
            cwd=Path("/labs"),
            environment={},
            registry=FakeRegistry(),
            docker=docker,
        )

        self.assertEqual(tuple(lab.name for lab in sleep_plan.labs), ("stopped",))
        self.assertEqual(sleep_plan.container_ids, ("stopped",))
        self.assertEqual(sleep_plan.image_ids, ())
        self.assertEqual(sleep_plan.preserved_shared_image_ids, ("sha256:shared",))

    def test_never_deployed_lab_resolves_topology_image(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            topology(root, image="example/router:1")
            docker = FakeDocker()
            docker.references = {"example/router:1": "sha256:resolved"}
            docker.images = {"resolved": "sha256:resolved"}

            sleep_plan = plan(
                (),
                cwd=root,
                environment={},
                registry=FakeRegistry(),
                docker=docker,
            )

        self.assertEqual(sleep_plan.image_ids, ("sha256:resolved",))
        self.assertFalse(sleep_plan.observations[0].ever_deployed)

    def test_topology_and_all_conflict(self) -> None:
        with self.assertRaises(SystemExit):
            parser("eclab sleep").parse_args(("-t", "lab.clab.yml", "--all"))

    def test_stopped_requires_all(self) -> None:
        with self.assertRaises(SystemExit):
            parse_options(("--stopped",), "eclab sleep")


class ExecutionTest(unittest.TestCase):
    def test_persists_before_removing_objects(self) -> None:
        events: list[str] = []

        class Registry(FakeRegistry):
            def upsert(self, records: tuple[LabRecord, ...]) -> None:
                events.append("registry")
                super().upsert(records)

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
        sleep_plan = SleepPlan(
            (LabUse("one", record.directory, None, record.image_ids, ("c",), True),),
            ("c",),
            ("sha256:image",),
            (),
            (record,),
        )
        logger = MagicMock()
        registry = Registry()

        code = execute(
            sleep_plan,
            registry=registry,
            docker=Docker(),
            logger=logger,
        )

        self.assertEqual(code, 0)
        self.assertEqual(events, ["registry", "container:c", "image:sha256:image"])

    def test_registry_failure_aborts_before_deletion(self) -> None:
        registry = FakeRegistry()
        registry.error = LabRegistryError("unavailable")
        docker = FakeDocker()
        sleep_plan = SleepPlan((), ("c",), ("sha256:image",), (), ())

        code = execute(
            sleep_plan,
            registry=registry,
            docker=docker,
            logger=MagicMock(),
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, [])
        self.assertEqual(docker.removed_images, [])

    def test_deletion_failures_do_not_stop_independent_attempts(self) -> None:
        docker = FakeDocker()
        docker.container_failures = {"bad"}
        sleep_plan = SleepPlan(
            (),
            ("bad", "good"),
            ("sha256:image",),
            (),
            (),
        )

        code = execute(
            sleep_plan,
            registry=FakeRegistry(),
            docker=docker,
            logger=MagicMock(),
        )

        self.assertEqual(code, 1)
        self.assertEqual(docker.removed_containers, ["good"])
        self.assertEqual(docker.removed_images, ["sha256:image"])


class DockerTest(unittest.TestCase):
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
        with patch.object(docker, "_run", return_value="") as run:
            docker.remove_image("sha256:image")
        run.assert_called_once_with(("image", "rm", "sha256:image"))


class PluginTest(unittest.TestCase):
    def test_package_declares_registry_before_sleep(self) -> None:
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )["project"]
        group = project["entry-points"][
            "engulf.plugins.v1.dependency.engulf_clab_sleep"
        ]
        self.assertEqual(
            group,
            {
                "engulf_clab.lab_registry": "preprocess=before; postprocess=none",
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
        self.assertEqual(tuple(goal), ("engulf_clab.sleep",))

    def test_schema_declares_sleep_and_destructive_scope(self) -> None:
        application = ApplicationMetadata(
            application_id="engulf-clab",
            display_name="ECLAB",
            vendor="Engulf",
            product="ECLAB",
            version="1",
            short_product_name="eclab",
        )
        names = {option.name for option in PLUGIN_SCHEMA.options(application)}
        self.assertTrue({"sleep", "-t", "--all", "--stopped"}.issubset(names))
        annotations = {
            annotation.subject: annotation
            for annotation in PLUGIN_SCHEMA.annotations(application)
        }
        self.assertEqual(
            annotations["sleep"].lifecycle,
            (LifecycleStage.BEFORE_GOAL,),
        )
        self.assertIn("are deleted", " ".join(annotations["sleep"].implies))

    def test_sleep_preempts_and_holds_mutation_lease(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "eclab"
        invocation = Invocation(("sleep", "--all"), Path("/labs"), {})
        registry = FakeRegistry()
        sleep_plan = SleepPlan((), (), (), (), ())

        with (
            patch("engulf_clab_sleep.plugin.lab_registry", return_value=registry),
            patch("engulf_clab_sleep.plugin.DockerClient") as docker,
            patch("engulf_clab_sleep.plugin.plan", return_value=sleep_plan) as planner,
            patch("engulf_clab_sleep.plugin.execute", return_value=0) as executor,
        ):
            result = SleepPlugin().before_goal(invocation, api)

        assert result is not None
        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(result.exit_code, 0)
        api.leases.assert_called_once_with(("eclab-sleep:docker",))
        planner.assert_called_once()
        executor.assert_called_once_with(
            sleep_plan,
            registry=registry,
            docker=docker.return_value,
            logger=api.logger,
        )

    def test_help_exits_before_registry_or_lease(self) -> None:
        api = MagicMock(spec=BeforeGoalAPI)
        api.get_context.return_value = None
        api.application = MagicMock(spec=ApplicationMetadata)
        api.application.short_product_name = "eclab"
        invocation = Invocation(("sleep", "--help"), Path("/labs"), {})

        with (
            patch("engulf_clab_sleep.plugin.lab_registry") as registry,
            self.assertRaises(SystemExit) as stopped,
        ):
            SleepPlugin().before_goal(invocation, api)

        self.assertEqual(stopped.exception.code, 0)
        registry.assert_not_called()
        api.leases.assert_not_called()


if __name__ == "__main__":
    unittest.main()
