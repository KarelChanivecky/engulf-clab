from __future__ import annotations

import ipaddress
import tomllib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engulf_api import ApplicationMetadata, InvocationAPI, RegistrationAPI
from engulf_clab_lab_parser import TopologySession
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    BeforeCallEvent,
    CallMode,
    CompletionContext,
    Shell,
)

from engulf_clab_sticky_ip.allocation import (
    Family,
    StickyIPError,
    TopologyRequest,
    parse_config,
)
from engulf_clab_sticky_ip.host import HostInventory
from engulf_clab_sticky_ip.plugin import (
    StickyIPPlugin,
    _allocation_plan,
    _mode,
    _Plan,
    _publish,
)
from engulf_clab_sticky_ip.registry import Allocation, Registry

_APPLICATION = ApplicationMetadata(
    application_id="engulf-clab",
    display_name="eclab",
    vendor="ECLAB",
    product="Engulf Containerlab",
    short_product_name="eclab",
    version="1.0.0",
)


class PluginTest(unittest.TestCase):
    @staticmethod
    def allocation(
        identifier: str,
        key: str,
        subnet: str,
        status: str,
        *,
        sequence: int = 1,
    ) -> Allocation:
        return Allocation(
            identifier,
            key,
            f"/tmp/{key}",
            key,
            Family.IPV4,
            f"network-{key}",
            subnet,
            1,
            {"a": str(ipaddress.ip_network(subnet).network_address + 10)},
            status,
            sequence,
            True,
        )

    def test_switches_are_registered_for_deploy_and_redeploy(self) -> None:
        registry = ArgumentRegistry()
        api = Mock(spec=RegistrationAPI)
        api.application = _APPLICATION

        StickyIPPlugin().register_arguments(registry, api)

        for name, environment in (
            ("--eclab-sticky-ipv6", "ECLAB_STICKY_IPV6"),
            ("--eclab-no-sticky-ip", "ECLAB_NO_STICKY_IP"),
        ):
            option = registry.find_exact(name)
            assert option is not None
            self.assertEqual(option.environment, environment)
            assert option.when is not None
            self.assertTrue(
                option.when(
                    CompletionContext(
                        Shell.BASH, "eclab", "containerlab", ("deploy", name), 1
                    )
                )
            )
            self.assertTrue(
                option.when(
                    CompletionContext(
                        Shell.BASH,
                        "eclab",
                        "containerlab",
                        ("redeploy", name),
                        1,
                    )
                )
            )
            self.assertFalse(
                option.when(
                    CompletionContext(
                        Shell.BASH, "eclab", "containerlab", ("destroy", name), 1
                    )
                )
            )

    def test_package_declares_catalog_application_and_ordering(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        entry_points = project["entry-points"]

        expected = {"engulf_clab.sticky_ip": "engulf_clab_sticky_ip:plugin"}
        self.assertEqual(
            entry_points["engulf.plugins.v1.goal.v1.org_engulf_executable_wrapper"],
            expected,
        )
        self.assertEqual(
            entry_points["engulf.plugins.v1.application.engulf_clab"], expected
        )
        self.assertEqual(
            entry_points["engulf.plugins.v1.dependency.engulf_clab_sticky_ip"],
            {
                "engulf_clab.lab_parser": "preprocess=before; postprocess=none",
                "engulf_clab.lab_writer": "preprocess=after; postprocess=none",
                "engulf_clab.schema": "preprocess=after; postprocess=none",
            },
        )

    def test_opt_out_wins_over_ipv6(self) -> None:
        self.assertEqual(
            _mode(
                ("deploy", "--eclab-sticky-ipv6", "--eclab-no-sticky-ip"),
                {},
            ),
            (True, Family.IPV6),
        )

    def test_redeploy_all_and_name_only_are_rejected(self) -> None:
        plugin = StickyIPPlugin()
        for args in (("redeploy", "--all"), ("redeploy", "--name", "lab")):
            with self.subTest(args=args):
                api = Mock(spec=InvocationAPI)
                contribution = plugin.analyze_call(
                    BeforeCallEvent("containerlab", args, CallMode.NORMAL), api
                )
                self.assertEqual(contribution.preempt_exit_code, 1)

    def test_opted_out_redeploy_all_keeps_native_call(self) -> None:
        contribution = StickyIPPlugin().analyze_call(
            BeforeCallEvent(
                "containerlab",
                ("redeploy", "--all", "--eclab-no-sticky-ip"),
                CallMode.NORMAL,
            ),
            Mock(spec=InvocationAPI),
        )
        self.assertIsNone(contribution)

    def test_new_allocation_skips_host_conflict_and_sets_fixed_slots(self) -> None:
        config = parse_config({"ECLAB_STICKY_IPV4_POOL": "10.70.0.0/23"})
        request = TopologyRequest(
            "lab",
            Family.IPV4,
            ("a", "b"),
            None,
            None,
            {},
        )
        inventory = HostInventory((), ())
        with patch(
            "engulf_clab_sticky_ip.plugin.probe_candidate",
            side_effect=(True, False),
        ):
            plan = _allocation_plan(
                Registry.empty(),
                config,
                request,
                Path("/tmp/lab"),
                "lab-key",
                inventory,
                destructive=False,
            )

        self.assertEqual(plan.subnet, ipaddress.ip_network("10.70.1.0/24"))
        self.assertEqual(plan.node_ips, {"a": "10.70.1.2", "b": "10.70.1.3"})

    def test_returning_lab_prefers_history_and_keeps_node_address(self) -> None:
        history = self.allocation("old", "lab-key", "10.71.0.0/24", "inactive")
        registry = Registry(
            0,
            1,
            {"ipv4": (0, -1), "ipv6": (0, -1)},
            (history,),
        )
        request = TopologyRequest("lab", Family.IPV4, ("a",), None, None, {})
        with patch("engulf_clab_sticky_ip.plugin.probe_candidate", return_value=False):
            plan = _allocation_plan(
                registry,
                parse_config({"ECLAB_STICKY_IPV4_POOL": "10.71.0.0/23"}),
                request,
                Path("/tmp/lab"),
                "lab-key",
                HostInventory((), ()),
                destructive=False,
            )

        self.assertEqual(plan.subnet, ipaddress.ip_network("10.71.0.0/24"))
        self.assertEqual(plan.node_ips, {"a": "10.71.0.10"})
        self.assertEqual(plan.evicted, (history,))

    def test_inactive_block_is_recycled_after_pool_is_exhausted(self) -> None:
        history = self.allocation("old", "other", "10.72.0.0/24", "inactive")
        registry = Registry(
            0,
            1,
            {"ipv4": (0, -1), "ipv6": (0, -1)},
            (history,),
        )
        request = TopologyRequest("lab", Family.IPV4, ("a",), None, None, {})
        with patch("engulf_clab_sticky_ip.plugin.probe_candidate", return_value=False):
            plan = _allocation_plan(
                registry,
                parse_config(
                    {
                        "ECLAB_STICKY_IP_MAX_LABS": "1",
                        "ECLAB_STICKY_IPV4_POOL": "10.72.0.0/24",
                    }
                ),
                request,
                Path("/tmp/lab"),
                "lab-key",
                HostInventory((), ()),
                destructive=False,
            )

        self.assertEqual(plan.subnet, ipaddress.ip_network("10.72.0.0/24"))
        self.assertEqual(plan.evicted, (history,))

    def test_active_lab_limit_fails_closed(self) -> None:
        active = self.allocation("active", "other", "10.73.0.0/24", "active")
        registry = Registry(
            0,
            1,
            {"ipv4": (0, -1), "ipv6": (0, -1)},
            (active,),
        )
        request = TopologyRequest("lab", Family.IPV4, ("a",), None, None, {})

        with self.assertRaisesRegex(StickyIPError, "active-lab limit"):
            _allocation_plan(
                registry,
                parse_config(
                    {
                        "ECLAB_STICKY_IP_MAX_LABS": "1",
                        "ECLAB_STICKY_IPV4_POOL": "10.73.0.0/23",
                    }
                ),
                request,
                Path("/tmp/lab"),
                "lab-key",
                HostInventory((), ()),
                destructive=False,
            )

    def test_publish_uses_containerlab_fixed_ip_fields(self) -> None:
        document = {
            "name": "lab",
            "topology": {"nodes": {"a": {}, "b": {}}},
        }
        session = TopologySession(Path("/tmp/lab.clab.yml"), document)
        request = TopologyRequest(
            "lab", Family.IPV6, ("a", "b"), None, None, {}
        )
        plan = _Plan(
            ipaddress.ip_network("fd00::/120"),
            "eclab-mgmt-lab",
            {"a": "fd00::2", "b": "fd00::3"},
            1,
            True,
            (),
            None,
        )

        _publish(session, Mock(spec=InvocationAPI), document, request, plan)
        rendered = session.materialize()

        self.assertEqual(
            rendered["mgmt"],
            {"network": "eclab-mgmt-lab", "ipv6-subnet": "fd00::/120"},
        )
        self.assertEqual(
            rendered["topology"]["nodes"]["a"]["mgmt-ipv6"], "fd00::2"
        )
        self.assertEqual(
            rendered["topology"]["nodes"]["b"]["mgmt-ipv6"], "fd00::3"
        )


if __name__ == "__main__":
    unittest.main()
