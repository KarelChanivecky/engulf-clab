from __future__ import annotations

import io
import signal
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from engulf_clab_sniff.extcap import _capture


def _process(return_code: int, stderr: bytes) -> Mock:
    process = Mock()
    process.stderr = io.BytesIO(stderr)
    process.wait.return_value = return_code
    process.poll.return_value = return_code
    return process


def test_capture_suppresses_normal_docker_and_tcpdump_stderr() -> None:
    process = _process(
        0,
        b"Unable to find image locally\n"
        b"tcpdump: listening on port3, link-type EN10MB\n"
        b"8 packets captured\n",
    )
    errors = io.StringIO()
    with (
        TemporaryDirectory() as directory,
        patch("engulf_clab_sniff.extcap.signal.signal", return_value=signal.SIG_DFL),
        patch("engulf_clab_sniff.extcap.subprocess.Popen", return_value=process) as popen,
        redirect_stderr(errors),
    ):
        result = _capture(["docker", "run"], Path(directory) / "capture.pcapng")

    assert result == 0
    assert errors.getvalue() == ""
    assert popen.call_args.kwargs["stderr"] is not None


def test_capture_forwards_stderr_only_when_helper_fails() -> None:
    process = _process(1, b"docker: Error response from daemon: no such container\n")
    errors = io.StringIO()
    with (
        TemporaryDirectory() as directory,
        patch("engulf_clab_sniff.extcap.signal.signal", return_value=signal.SIG_DFL),
        patch("engulf_clab_sniff.extcap.subprocess.Popen", return_value=process),
        redirect_stderr(errors),
    ):
        result = _capture(["docker", "run"], Path(directory) / "capture.pcapng")

    assert result == 1
    assert errors.getvalue() == "docker: Error response from daemon: no such container\n"
