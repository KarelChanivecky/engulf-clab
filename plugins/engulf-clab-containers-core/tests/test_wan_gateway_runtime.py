from __future__ import annotations

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from engulf_clab_containers_core.wan_gateway_runtime import (
    GatewayError,
    configure_addressing,
    configure_nat,
    dnsmasq_arguments,
    parse_config,
)


class ParseConfigTest(unittest.TestCase):
    def test_defaults(self) -> None:
        config = parse_config({})
        self.assertEqual(str(config.subnet), "198.19.0.0/24")
        self.assertEqual(str(config.gateway), "198.19.0.1")
        self.assertEqual(str(config.pool_start), "198.19.0.100")
        self.assertEqual(str(config.pool_end), "198.19.0.200")
        self.assertEqual(str(config.dns), "1.1.1.1")
        self.assertEqual(config.lease_time, 43200)

    def test_overrides(self) -> None:
        config = parse_config(
            {
                "ECLAB_DHCP_SUBNET": "10.0.0.0/24",
                "ECLAB_DHCP_GATEWAY": "10.0.0.1",
                "ECLAB_DHCP_POOL_START": "10.0.0.50",
                "ECLAB_DHCP_POOL_END": "10.0.0.60",
                "ECLAB_DHCP_DNS": "10.0.0.1",
                "ECLAB_DHCP_LEASE_TIME": "300",
            }
        )
        self.assertEqual(str(config.pool_start), "10.0.0.50")
        self.assertEqual(config.lease_time, 300)

    def test_gateway_outside_subnet_is_rejected(self) -> None:
        with self.assertRaisesRegex(GatewayError, "inside"):
            parse_config({"ECLAB_DHCP_GATEWAY": "192.0.2.1"})

    def test_gateway_inside_pool_is_rejected(self) -> None:
        with self.assertRaisesRegex(GatewayError, "outside the DHCP pool"):
            parse_config({"ECLAB_DHCP_GATEWAY": "198.19.0.150"})

    def test_pool_start_after_pool_end_is_rejected(self) -> None:
        with self.assertRaisesRegex(GatewayError, "must not exceed"):
            parse_config(
                {
                    "ECLAB_DHCP_POOL_START": "198.19.0.200",
                    "ECLAB_DHCP_POOL_END": "198.19.0.100",
                }
            )

    def test_non_positive_lease_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(GatewayError, "positive"):
            parse_config({"ECLAB_DHCP_LEASE_TIME": "0"})

    def test_ipv6_subnet_is_rejected(self) -> None:
        with self.assertRaisesRegex(GatewayError, "IPv4"):
            parse_config({"ECLAB_DHCP_SUBNET": "2001:db8::/64"})


class ConfigureTest(unittest.TestCase):
    @patch("engulf_clab_containers_core.wan_gateway_runtime._run")
    def test_addressing_assigns_gateway_and_brings_interface_up(self, run) -> None:
        run.side_effect = lambda *args, **kwargs: CompletedProcess(args, 0, b"", b"")
        config = parse_config({})

        configure_addressing(config, "eth1")

        commands = [item.args for item in run.call_args_list]
        self.assertIn(
            ("ip", "addr", "replace", "198.19.0.1/24", "dev", "eth1"),
            commands,
        )
        self.assertIn(("ip", "link", "set", "eth1", "up"), commands)

    @patch("engulf_clab_containers_core.wan_gateway_runtime._run")
    def test_nat_masquerades_subnet_out_eth0(self, run) -> None:
        run.side_effect = lambda *args, **kwargs: CompletedProcess(args, 0, b"", b"")
        config = parse_config({})

        configure_nat(config, "eth1")

        commands = [item.args for item in run.call_args_list]
        self.assertIn(
            (
                "iptables", "-t", "nat", "-A", "ECLAB_DHCP_SNAT",
                "-s", "198.19.0.0/24", "-o", "eth0", "-j", "MASQUERADE",
            ),
            commands,
        )
        self.assertIn(
            ("iptables", "-A", "ECLAB_DHCP_FORWARD", "-i", "eth1", "-o", "eth0", "-j", "ACCEPT"),
            commands,
        )


class DnsmasqArgumentsTest(unittest.TestCase):
    def test_binds_single_interface_and_disables_dns(self) -> None:
        config = parse_config({})

        arguments = dnsmasq_arguments(config, "eth1")

        self.assertIn("--port=0", arguments)
        self.assertIn("--interface=eth1", arguments)
        self.assertIn("--dhcp-range=198.19.0.100,198.19.0.200,43200s", arguments)
        self.assertIn("--dhcp-option=option:router,198.19.0.1", arguments)
        self.assertIn("--dhcp-option=option:dns-server,1.1.1.1", arguments)


if __name__ == "__main__":
    unittest.main()
