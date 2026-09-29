from __future__ import annotations

import errno
import importlib.util
import io
import itertools
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import call, patch

_RUNTIME_PATH = (
    Path(__file__).parents[1]
    / "src/engulf_clab_containers_core/containers/host-connector/runtime.py"
)
_RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "eclab_host_connector_runtime", _RUNTIME_PATH
)
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
            state = network / "eth1/operstate"
            state.write_text("up\n")

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
            state.write_text("down\n")
            self.assertEqual(data_interfaces(network, sysctl), ())
            state.unlink()
            self.assertEqual(data_interfaces(network, sysctl), ())

    def test_temporary_veth_names_are_ignored_and_custom_names_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network = root / "net"
            sysctl = root / "sysctl"
            for name in ("lo", "eth0", "clab-123456", "uplink"):
                (network / name).mkdir(parents=True)
                (network / name / "operstate").write_text("up\n")
                for family, setting in (
                    ("ipv4", "proxy_arp"),
                    ("ipv4", "rp_filter"),
                    ("ipv6", "proxy_ndp"),
                ):
                    target = sysctl / family / "conf" / name / setting
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
            self.assertEqual(data_interfaces(network, sysctl), ("uplink",))

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


class StartupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.elapsed = 0.0
        self.enterContext(patch.object(runtime.time, "monotonic", lambda: self.elapsed))
        self.enterContext(patch.object(runtime.time, "sleep", self.advance))
        self.mappings = parse_mappings({"ECLAB_CONNECT_HOST": "10.0.0.50;192.0.2.50"})

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds

    def test_waits_for_interface_to_be_ready(self) -> None:
        with (
            patch.object(runtime, "data_interfaces", side_effect=[(), (), ("eth1",), ("eth1",)]),
            patch.object(runtime, "configure") as configure_mock,
        ):
            self.assertEqual(runtime.activate_interfaces(self.mappings), ("eth1",))
        configure_mock.assert_called_once_with(self.mappings, ("eth1",))
        self.assertAlmostEqual(self.elapsed, 0.4)

    def test_retries_interface_races_during_configuration(self) -> None:
        errors = (
            OSError(errno.ENODEV, "No such device"),
            ConnectorError("cannot set disappeared sysctl"),
            CalledProcessError(1, ["ip", "route"]),
        )
        for error in errors:
            with (
                self.subTest(error=error),
                patch.object(
                    runtime,
                    "data_interfaces",
                    side_effect=[("old-name",), (), ("eth1",), ("eth1",)],
                ),
                patch.object(runtime, "configure", side_effect=[error, None]) as configure_mock,
            ):
                self.assertEqual(runtime.activate_interfaces(self.mappings), ("eth1",))
                self.assertEqual(configure_mock.call_count, 2)

    def test_interface_arriving_during_last_poll_interval_is_accepted(self) -> None:
        self.elapsed = 1000.0
        with (
            patch.object(
                runtime,
                "data_interfaces",
                side_effect=lambda: ("eth1",) if self.elapsed >= 1014.95 else (),
            ),
            patch.object(runtime, "configure") as configure_mock,
        ):
            self.assertEqual(runtime.activate_interfaces(self.mappings), ("eth1",))
        self.assertAlmostEqual(self.elapsed, 1015.0)
        configure_mock.assert_called_once_with(self.mappings, ("eth1",))

    def test_does_not_hide_configuration_errors_on_ready_interfaces(self) -> None:
        for error in (
            OSError(errno.EPERM, "Operation not permitted"),
            ConnectorError("invalid policy rule"),
            CalledProcessError(1, ["iptables"]),
        ):
            with (
                self.subTest(error=error),
                patch.object(runtime, "data_interfaces", return_value=("eth1",)),
                patch.object(runtime, "configure", side_effect=error),
                self.assertRaises(type(error)) as raised,
            ):
                runtime.activate_interfaces(self.mappings)
            self.assertIs(raised.exception, error)
        self.assertEqual(self.elapsed, 0)

    def test_interface_changes_after_configuration_are_retried(self) -> None:
        with (
            patch.object(
                runtime,
                "data_interfaces",
                side_effect=[("eth1",), (), ("eth2",), ("eth2",)],
            ),
            patch.object(runtime, "configure") as configure_mock,
        ):
            self.assertEqual(runtime.activate_interfaces(self.mappings), ("eth2",))
        self.assertEqual(configure_mock.call_count, 2)

    def test_repeated_interface_races_do_not_extend_deadline(self) -> None:
        with (
            patch.object(runtime, "data_interfaces", side_effect=itertools.cycle([("eth1",), ()])),
            patch.object(runtime, "configure", side_effect=OSError(errno.ENODEV, "No such device")),
            self.assertRaisesRegex(ConnectorError, "WARNING:.*15s"),
        ):
            runtime.activate_interfaces(self.mappings)
        self.assertAlmostEqual(self.elapsed, 15)

    def test_missing_interface_warns_and_exits_within_15_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "ready"
            ready.touch()  # A restarted process must not inherit stale health.
            with (
                patch.object(runtime, "_READY", ready),
                patch.dict(
                    runtime.os.environ, {"ECLAB_CONNECT_HOST": "10.0.0.50;192.0.2.50"}, clear=True
                ),
                patch.object(runtime, "data_interfaces", return_value=()),
                patch.object(runtime, "configure") as configure_mock,
                patch.object(runtime.sys, "stderr", new_callable=io.StringIO) as stderr,
            ):
                self.assertEqual(runtime.main(), 1)
                self.assertIn(
                    "WARNING: no lab interface became ready within 15s", stderr.getvalue()
                )
                self.assertFalse(ready.exists())
                configure_mock.assert_not_called()
        self.assertAlmostEqual(self.elapsed, 15)

    def test_lost_interface_clears_health_and_gets_bounded_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "ready"

            def interfaces() -> tuple[str, ...]:
                if self.elapsed < 1:
                    return ("eth1",)
                if self.elapsed > 1:
                    self.assertFalse(ready.exists())
                return ()

            with (
                patch.object(runtime, "_READY", ready),
                patch.dict(
                    runtime.os.environ, {"ECLAB_CONNECT_HOST": "10.0.0.50;192.0.2.50"}, clear=True
                ),
                patch.object(runtime, "data_interfaces", side_effect=interfaces),
                patch.object(runtime, "configure") as configure_mock,
                patch.object(runtime.sys, "stdout", new_callable=io.StringIO) as stdout,
                patch.object(runtime.sys, "stderr", new_callable=io.StringIO),
            ):
                self.assertEqual(runtime.main(), 1)
                self.assertIn("host-connector ready on eth1", stdout.getvalue())
                self.assertFalse(ready.exists())
                configure_mock.assert_called_once()
        self.assertAlmostEqual(self.elapsed, 16)


if __name__ == "__main__":
    unittest.main()
