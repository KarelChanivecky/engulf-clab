from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import call, patch

_RUNTIME_PATH = (
    Path(__file__).parents[1]
    / "src/engulf_clab_containers_core/containers/host-connector/runtime.py"
)
_RUNTIME_SPEC = importlib.util.spec_from_file_location("eclab_host_connector_runtime", _RUNTIME_PATH)
assert _RUNTIME_SPEC is not None and _RUNTIME_SPEC.loader is not None
runtime = importlib.util.module_from_spec(_RUNTIME_SPEC)
sys.modules[_RUNTIME_SPEC.name] = runtime
_RUNTIME_SPEC.loader.exec_module(runtime)

ConnectorError = runtime.ConnectorError
configure = runtime.configure
data_interfaces = runtime.data_interfaces
parse_mappings = runtime.parse_mappings


class RuntimeTest(unittest.TestCase):
    def test_data_interface_waits_for_kernel_sysctl_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network = root / "sys/class/net"
            sysctl = root / "proc/sys/net"
            for name in ("lo", "eth0", "eth1"):
                (network / name).mkdir(parents=True)

            self.assertEqual(data_interfaces(network, sysctl), ())

            for family, setting in (
                ("ipv4", "proxy_arp"),
                ("ipv4", "rp_filter"),
                ("ipv6", "proxy_ndp"),
            ):
                target = sysctl / family / "conf/eth1" / setting
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()

            self.assertEqual(data_interfaces(network, sysctl), ("eth1",))

    def test_sparse_dual_stack_mappings(self) -> None:
        mappings = parse_mappings(
            {
                "ECLAB_CONNECT_HOST": "10.0.0.10;192.0.2.10",
                "ECLAB_CONNECT_HOST_7": "2001:db8::10;2001:db8:1::10",
            }
        )
        self.assertEqual([item.index for item in mappings], [0, 7])
        self.assertEqual([item.vip.version for item in mappings], [4, 6])

    def test_zero_alias_and_mixed_family_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConnectorError, "aliases"):
            parse_mappings(
                {
                    "ECLAB_CONNECT_HOST": "10.0.0.1;192.0.2.1",
                    "ECLAB_CONNECT_HOST_0": "10.0.0.2;192.0.2.2",
                }
            )
        with self.assertRaisesRegex(ConnectorError, "same address family"):
            parse_mappings({"ECLAB_CONNECT_HOST": "10.0.0.1;2001:db8::1"})

    def test_duplicate_vip_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConnectorError, "duplicate VIP"):
            parse_mappings(
                {
                    "ECLAB_CONNECT_HOST": "10.0.0.1;192.0.2.1",
                    "ECLAB_CONNECT_HOST_2": "10.0.0.1;192.0.2.2",
                }
            )

    @patch.object(runtime, "_write_sysctl")
    @patch.object(runtime, "_run")
    @patch.object(runtime.socket, "if_nametoindex")
    def test_every_non_management_interface_gets_vips_and_its_own_reply_route(
        self, interface_index, run, _write_sysctl
    ) -> None:
        interface_index.side_effect = (2, 9)
        run.side_effect = lambda *args, **kwargs: CompletedProcess(args, 0, b"", b"")
        mappings = parse_mappings({"ECLAB_CONNECT_HOST": "10.0.0.50;192.0.2.50"})

        configure(mappings, ("eth1", "eth7"))

        commands = [item.args for item in run.call_args_list]
        self.assertIn(
            ("ip", "-4", "neigh", "replace", "proxy", "10.0.0.50", "dev", "eth1"),
            commands,
        )
        self.assertIn(
            ("ip", "-4", "neigh", "replace", "proxy", "10.0.0.50", "dev", "eth7"),
            commands,
        )
        self.assertIn(
            (
                "ip",
                "-4",
                "route",
                "replace",
                "default",
                "dev",
                "eth1",
                "table",
                "10002",
            ),
            commands,
        )
        self.assertIn(
            (
                "ip",
                "-4",
                "route",
                "replace",
                "default",
                "dev",
                "eth7",
                "table",
                "10009",
            ),
            commands,
        )
        self.assertIn(
            (
                "iptables",
                "-t",
                "mangle",
                "-A",
                "ECLAB_MARK",
                "-i",
                "eth1",
                "-d",
                "10.0.0.50",
                "-m",
                "conntrack",
                "--ctstate",
                "NEW",
                "-j",
                "CONNMARK",
                "--set-mark",
                "1002",
            ),
            commands,
        )
        self.assertNotIn(
            (
                "iptables",
                "-t",
                "mangle",
                "-A",
                "ECLAB_MARK",
                "-m",
                "mark",
                "!",
                "--mark",
                "0",
                "-j",
                "CONNMARK",
                "--save-mark",
            ),
            commands,
        )
        self.assertEqual(
            _write_sysctl.call_args_list,
            [
                call("ipv4", "eth1", "proxy_arp", "1"),
                call("ipv4", "eth1", "rp_filter", "0"),
                call("ipv6", "eth1", "proxy_ndp", "1"),
                call("ipv4", "eth7", "proxy_arp", "1"),
                call("ipv4", "eth7", "rp_filter", "0"),
                call("ipv6", "eth7", "proxy_ndp", "1"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
