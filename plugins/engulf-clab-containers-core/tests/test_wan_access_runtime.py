from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch

_RUNTIME_PATH = (
    Path(__file__).parents[1]
    / "src/engulf_clab_containers_core/containers/wan-access/wan_access_runtime.py"
)
_RUNTIME_SPEC = importlib.util.spec_from_file_location("eclab_wan_access_runtime", _RUNTIME_PATH)
assert _RUNTIME_SPEC is not None and _RUNTIME_SPEC.loader is not None
runtime = importlib.util.module_from_spec(_RUNTIME_SPEC)
sys.modules[_RUNTIME_SPEC.name] = runtime
_RUNTIME_SPEC.loader.exec_module(runtime)

WanAccessError = runtime.WanAccessError
activate_lab_interface = runtime.activate_lab_interface
configure_dhcp_addressing = runtime.configure_dhcp_addressing
configure_interface = runtime.configure_interface
configure_nat = runtime.configure_nat
dnsmasq_arguments = runtime.dnsmasq_arguments
parse_dhcp_config = runtime.parse_dhcp_config
start_dhcp = runtime.start_dhcp


class ParseDhcpConfigTest(unittest.TestCase):
    def test_dhcp_is_disabled_without_dhcp_environment(self) -> None:
        self.assertIsNone(parse_dhcp_config({}))

    def test_any_supported_dhcp_variable_enables_defaults(self) -> None:
        config = parse_dhcp_config({"ECLAB_DHCP_DNS": "1.1.1.1"})
        assert config is not None
        self.assertEqual(str(config.subnet), "198.19.0.0/24")
        self.assertEqual(str(config.gateway), "198.19.0.1")
        self.assertEqual(str(config.pool_start), "198.19.0.100")
        self.assertEqual(str(config.pool_end), "198.19.0.200")
        self.assertEqual(str(config.dns), "1.1.1.1")
        self.assertEqual(config.lease_time, 43200)

    def test_overrides(self) -> None:
        config = parse_dhcp_config(
            {
                "ECLAB_DHCP_SUBNET": "10.0.0.0/24",
                "ECLAB_DHCP_GATEWAY": "10.0.0.1",
                "ECLAB_DHCP_POOL_START": "10.0.0.50",
                "ECLAB_DHCP_POOL_END": "10.0.0.60",
                "ECLAB_DHCP_DNS": "10.0.0.1",
                "ECLAB_DHCP_LEASE_TIME": "300",
            }
        )
        assert config is not None
        self.assertEqual(str(config.pool_start), "10.0.0.50")
        self.assertEqual(config.lease_time, 300)

    def test_gateway_outside_subnet_is_rejected(self) -> None:
        with self.assertRaisesRegex(WanAccessError, "inside"):
            parse_dhcp_config({"ECLAB_DHCP_GATEWAY": "192.0.2.1"})

    def test_gateway_inside_pool_is_rejected(self) -> None:
        with self.assertRaisesRegex(WanAccessError, "outside the DHCP pool"):
            parse_dhcp_config({"ECLAB_DHCP_GATEWAY": "198.19.0.150"})

    def test_pool_start_after_pool_end_is_rejected(self) -> None:
        with self.assertRaisesRegex(WanAccessError, "must not exceed"):
            parse_dhcp_config(
                {
                    "ECLAB_DHCP_POOL_START": "198.19.0.200",
                    "ECLAB_DHCP_POOL_END": "198.19.0.100",
                }
            )

    def test_non_positive_lease_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(WanAccessError, "positive"):
            parse_dhcp_config({"ECLAB_DHCP_LEASE_TIME": "0"})

    def test_ipv6_subnet_is_rejected(self) -> None:
        with self.assertRaisesRegex(WanAccessError, "IPv4"):
            parse_dhcp_config({"ECLAB_DHCP_SUBNET": "2001:db8::/64"})


class ConfigureTest(unittest.TestCase):
    @patch.object(runtime, "lab_interfaces", return_value=("eth1",))
    @patch.object(runtime, "configure_interface")
    @patch.object(runtime, "wait_for_lab_interface", side_effect=("clab-deadbeef", "eth1"))
    def test_transient_containerlab_interface_rename_is_retried(
        self, wait, configure, interfaces
    ) -> None:
        configure.side_effect = (
            CalledProcessError(1, ("ip", "link", "set", "clab-deadbeef", "up")),
            None,
        )

        self.assertEqual(activate_lab_interface(), "eth1")

        self.assertEqual(wait.call_count, 2)
        interfaces.assert_called_once_with()

    @patch.object(runtime, "lab_interfaces", return_value=("eth1",))
    @patch.object(runtime, "configure_interface")
    @patch.object(runtime, "wait_for_lab_interface", return_value="eth1")
    def test_failure_on_existing_interface_is_not_retried(
        self, wait, configure, interfaces
    ) -> None:
        configure.side_effect = CalledProcessError(
            1, ("ip", "link", "set", "eth1", "up")
        )

        with self.assertRaises(CalledProcessError):
            activate_lab_interface()

        wait.assert_called_once_with()
        interfaces.assert_called_once_with()

    @patch.object(runtime, "_run")
    def test_interface_is_brought_up_without_dhcp(self, run) -> None:
        run.side_effect = lambda *args, **kwargs: CompletedProcess(args, 0, b"", b"")

        configure_interface("eth1")

        commands = [item.args for item in run.call_args_list]
        self.assertEqual(commands, [("ip", "link", "set", "eth1", "up")])

    @patch.object(runtime, "_run")
    def test_dhcp_addressing_assigns_gateway(self, run) -> None:
        run.side_effect = lambda *args, **kwargs: CompletedProcess(args, 0, b"", b"")
        config = parse_dhcp_config({"ECLAB_DHCP_SUBNET": "198.19.0.0/24"})
        assert config is not None

        configure_dhcp_addressing(config, "eth1")

        commands = [item.args for item in run.call_args_list]
        self.assertIn(
            ("ip", "addr", "replace", "198.19.0.1/24", "dev", "eth1"),
            commands,
        )

    @patch.object(runtime, "_run")
    def test_nat_masquerades_all_lab_traffic_out_eth0(self, run) -> None:
        run.side_effect = lambda *args, **kwargs: CompletedProcess(args, 0, b"", b"")

        configure_nat("eth1")

        commands = [item.args for item in run.call_args_list]
        self.assertIn(
            (
                "iptables", "-t", "nat", "-A", "ECLAB_WAN_ACCESS_NAT",
                "-o", "eth0", "-j", "MASQUERADE",
            ),
            commands,
        )
        self.assertIn(
            (
                "iptables", "-A", "ECLAB_WAN_ACCESS_FORWARD",
                "-i", "eth1", "-o", "eth0", "-j", "ACCEPT",
            ),
            commands,
        )
        self.assertIn(
            (
                "iptables", "-A", "ECLAB_WAN_ACCESS_FORWARD",
                "-i", "eth0", "-o", "eth1",
                "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT",
            ),
            commands,
        )


class DnsmasqArgumentsTest(unittest.TestCase):
    @patch.object(runtime.subprocess, "Popen")
    def test_dhcp_process_starts_only_with_dhcp_config(self, popen) -> None:
        self.assertIsNone(start_dhcp(None, "eth1"))
        popen.assert_not_called()

        config = parse_dhcp_config({"ECLAB_DHCP_DNS": "1.1.1.1"})
        assert config is not None
        self.assertIs(start_dhcp(config, "eth1"), popen.return_value)
        popen.assert_called_once_with(dnsmasq_arguments(config, "eth1"))

    def test_binds_single_interface_and_disables_dns(self) -> None:
        config = parse_dhcp_config({"ECLAB_DHCP_SUBNET": "198.19.0.0/24"})
        assert config is not None

        arguments = dnsmasq_arguments(config, "eth1")

        self.assertIn("--port=0", arguments)
        self.assertIn("--interface=eth1", arguments)
        self.assertIn("--dhcp-range=198.19.0.100,198.19.0.200,43200s", arguments)
        self.assertIn("--dhcp-option=option:router,198.19.0.1", arguments)
        self.assertIn("--dhcp-option=option:dns-server,1.1.1.1", arguments)


if __name__ == "__main__":
    unittest.main()
