from __future__ import annotations

import contextlib
import http.server
import importlib.util
import json
import os
import shutil
import ssl
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ASSET = (
    Path(__file__).resolve().parents[1]
    / "src/engulf_clab_pki_linux_core/asset/opt/eclab-pki/runtime.py"
)


def load_runtime() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eclab_pki_test_runtime", ASSET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity(root: Path, name: str, eku: str) -> dict[str, object]:
    relative = Path("issued") / name
    directory = root / relative
    directory.mkdir(parents=True)
    for filename in ("certificate.pem", "private-key.pem", "chain.pem", "full-chain.pem"):
        (directory / filename).write_text(filename + "\n")
    return {
        "identity_id": f"local/{name}",
        "path": str(relative),
        "extended_key_usage": [eku],
    }


def capabilities(runtime: ModuleType, *enabled: str) -> dict[str, bool]:
    return {program: program in enabled for program in runtime.PROGRAMS}


def test_curl_and_nginx_selectors_write_owned_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    runtime.STATE = tmp_path / "state"
    root = tmp_path / "inventory"
    client = identity(root, "client", "client_auth")
    server = identity(root, "server", "server_auth")
    monkeypatch.setenv("ECLAB_PKI_IDENTITY_CURL", "client")
    monkeypatch.setenv("ECLAB_PKI_IDENTITY_NGINX", "local/server")
    environment: dict[str, str] = {}

    runtime.configure_selectors(
        root,
        [client, server],
        [],
        capabilities(runtime, "CURL", "NGINX"),
        environment,
    )

    curlrc = runtime.STATE / "curl" / ".curlrc"
    nginx = runtime.STATE / "nginx" / "identity.conf"
    assert environment["CURL_HOME"] == str(curlrc.parent)
    assert "private-key.pem" in curlrc.read_text()
    assert environment["ECLAB_PKI_NGINX_FRAGMENT"] == str(nginx)
    nginx_text = nginx.read_text()
    assert "ssl_certificate " in nginx_text and "full-chain.pem" in nginx_text
    assert "ssl_certificate_key " in nginx_text and "private-key.pem" in nginx_text
    assert "ssl_trusted_certificate " in nginx_text and "chain.pem" in nginx_text


def test_adapter_files_are_removed_when_selectors_disappear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    runtime.STATE = tmp_path / "state"
    for target in (
        runtime.STATE / "curl" / ".curlrc",
        runtime.STATE / "nginx" / "identity.conf",
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stale\n")
    monkeypatch.delenv("ECLAB_PKI_IDENTITY_DEFAULT", raising=False)
    monkeypatch.delenv("ECLAB_PKI_IDENTITY_CURL", raising=False)
    monkeypatch.delenv("ECLAB_PKI_IDENTITY_NGINX", raising=False)

    runtime.configure_selectors(
        tmp_path, [], [], capabilities(runtime, "CURL", "NGINX"), {}
    )

    assert not (runtime.STATE / "curl" / ".curlrc").exists()
    assert not (runtime.STATE / "nginx" / "identity.conf").exists()


def test_nginx_rejects_a_client_only_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    runtime.STATE = tmp_path / "state"
    root = tmp_path / "inventory"
    client = identity(root, "client", "client_auth")
    monkeypatch.setenv("ECLAB_PKI_IDENTITY_NGINX", "client")

    with pytest.raises(RuntimeError, match="requires server_auth"):
        runtime.configure_selectors(
            root, [client], [], capabilities(runtime, "NGINX"), {}
        )


def test_environment_file_exports_every_name(tmp_path: Path) -> None:
    runtime = load_runtime()
    runtime.STATE = tmp_path / "state"

    runtime.write_environment({"CURL_HOME": "/opt/eclab-pki/state/curl", "SPACED": "a b"})

    written = (runtime.STATE / "environment").read_text()
    # The file is sourced, so plain assignments would stay shell-local and never
    # reach curl, nginx, or any other adapter the selectors configure.
    assert written.splitlines() == [
        "export CURL_HOME=/opt/eclab-pki/state/curl",
        "export SPACED='a b'",
    ]


def run_tool(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def nss_material(tmp_path: Path) -> Path:
    for tool in ("openssl", "certutil", "pk12util"):
        if not shutil.which(tool):
            pytest.skip(f"real NSS integration tests require {tool}")
    root = tmp_path / "inventory"
    for serial, (name, issuer, ca, usage) in enumerate((
        ("root", None, True, None),
        ("issuing", "root", True, None),
        ("inspection", None, True, None),
        ("unrelated", None, True, None),
        ("client", "issuing", False, "clientAuth"),
        ("secondary", "issuing", False, "clientAuth"),
        ("original", "issuing", False, "serverAuth"),
        ("intercepted", "inspection", False, "serverAuth"),
        ("unselected", "root", False, "serverAuth"),
    ), start=1):
        directory = root / name
        directory.mkdir(parents=True)
        key = directory / "private-key.pem"
        request = directory / "request.pem"
        run_tool(
            "openssl", "req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
            "-nodes", "-keyout", str(key), "-out", str(request), "-subj", f"/CN=Test {name} CA",
        )
        extensions = directory / "extensions"
        extensions.write_text(
            f"basicConstraints=critical,CA:{'TRUE' if ca else 'FALSE'}\n"
            f"keyUsage=critical,{'keyCertSign,cRLSign' if ca else 'digitalSignature'}\n"
            "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
            # The loopback address is a name a real browser can be pointed at.
            + (f"extendedKeyUsage={usage}\nsubjectAltName=DNS:server.demo.test,IP:127.0.0.1\n" if usage else "")
        )
        signer = (
            ("-CA", str(root / issuer / "certificate.pem"),
             "-CAkey", str(root / issuer / "private-key.pem"))
            if issuer else ("-signkey", str(key))
        )
        run_tool(
            "openssl", "x509", "-req", "-in", str(request), *signer,
            "-set_serial", str(serial), "-days", "2", "-extfile", str(extensions),
            "-out", str(directory / "certificate.pem"),
        )
    leaves = []
    for name in ("client", "secondary"):
        directory = root / name
        chain = (root / "issuing/certificate.pem").read_text() + (root / "root/certificate.pem").read_text()
        (directory / "chain.pem").write_text(chain)
        (directory / "full-chain.pem").write_text((directory / "certificate.pem").read_text() + chain)
        leaves.append({"identity_id": f"local/{name}", "path": name, "extended_key_usage": ["client_auth"]})
    (root / "inventory.json").write_text(json.dumps({"version": 2, "issued_identities": leaves}))
    (root / "trust").mkdir()
    # Inspection is deliberately absent from every client identity's chain.
    (root / "trust/ca-bundle.pem").write_text(
        (root / "inspection/certificate.pem").read_text()
        + (root / "issuing/certificate.pem").read_text()
    )
    return root


@pytest.fixture
def browser_runtime(
    nss_material: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> ModuleType:
    runtime = load_runtime()
    runtime.STATE = tmp_path / "state"
    for name in tuple(runtime.os.environ):
        if name.startswith("ECLAB_PKI_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("ECLAB_PKI_ROOT", str(nss_material))
    monkeypatch.setenv("ECLAB_PKI_SYSTEM_TRUST", "isolated")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path / "home")
    which = shutil.which
    monkeypatch.setattr(
        runtime.shutil, "which",
        lambda name: f"/test/{name}" if name in {"chromium", "firefox"} else which(name),
    )
    return runtime


def nss_listing(database: Path) -> dict[str, str]:
    return {
        nickname: trust for line in run_tool("certutil", "-L", "-d", f"sql:{database}").splitlines()
        if len(parts := line.rsplit(None, 1)) == 2 and parts[1].count(",") == 2
        for nickname, trust in [parts]
    }


def assert_server_trust(root: Path, database: Path, name: str, trusted: bool) -> None:
    run_tool(
        "certutil", "-A", "-d", f"sql:{database}", "-n", name, "-t", ",,", "-a",
        "-i", str(root / name / "certificate.pem"),
    )
    result = subprocess.run(
        ["certutil", "-V", "-d", f"sql:{database}", "-n", name, "-u", "V", "-e"],
        capture_output=True, text=True, check=False,
    )
    assert (result.returncode == 0) == trusted, result.stdout + result.stderr


def test_chromium_databases_cover_every_consulted_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = load_runtime()
    home = tmp_path / "home"
    monkeypatch.setattr(runtime.Path, "home", lambda: home)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    # Chromium consults ~/.pki/nssdb first and the XDG data directory only when
    # that path is absent, so a node that carries trust in just one can still
    # meet a build that reads the other.
    assert runtime.nss_databases() == [home / ".pki/nssdb", home / ".local/share/pki/nssdb"]

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert runtime.nss_databases() == [home / ".pki/nssdb", tmp_path / "xdg/pki/nssdb"]

    # A relative XDG_DATA_HOME is invalid and the specification says to ignore it.
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")
    assert runtime.nss_databases() == [home / ".pki/nssdb", home / ".local/share/pki/nssdb"]


def test_chromium_databases_deduplicate_a_linked_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = load_runtime()
    home = tmp_path / "home"
    monkeypatch.setattr(runtime.Path, "home", lambda: home)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    (home / ".local/share/pki/nssdb").mkdir(parents=True)
    (home / ".pki").mkdir()
    (home / ".pki/nssdb").symlink_to(home / ".local/share/pki/nssdb")

    # Device and inode identity, rather than path resolution, is what collapses
    # a shared database, so an image that bind-mounts one path onto the other
    # is recognised the same way this symlink is.
    assert runtime.nss_databases() == [home / ".pki/nssdb"]


@pytest.mark.parametrize("existing", [False, True])
def test_browser_startup_trusts_selected_anchors_and_preserves_identities(
    nss_material: Path, browser_runtime: ModuleType, existing: bool,
) -> None:
    runtime, root = browser_runtime, nss_material
    databases = (*runtime.nss_databases(), runtime.STATE / "firefox/all")
    if existing:
        leaves = json.loads((root / "inventory.json").read_text())["issued_identities"]
        for database in databases:
            runtime.nss_import(root, leaves, database)
            assert nss_listing(database) == {
                "local/client": "u,u,u", "local/secondary": "u,u,u",
                "Test issuing CA": ",,", "Test root CA": ",,",
            }

    runtime.main()
    for database in databases:
        listing = nss_listing(database)
        inspection = next(iter(runtime.nss_certificates(root / "inspection/certificate.pem")))
        assert listing == {
            "local/client": "u,u,u", "local/secondary": "u,u,u",
            "Test issuing CA": "CT,c,c", "Test root CA": ",,", inspection: "CT,c,c",
        }
        assert_server_trust(root, database, "original", True)
        assert_server_trust(root, database, "intercepted", True)
        assert_server_trust(root, database, "unselected", False)

    before = [nss_listing(database) for database in databases]
    runtime.main()
    assert [nss_listing(database) for database in databases] == before


@pytest.mark.parametrize("pk12_available", [False, True])
def test_browser_trust_without_client_identities(
    nss_material: Path, browser_runtime: ModuleType,
    monkeypatch: pytest.MonkeyPatch, pk12_available: bool,
) -> None:
    runtime, root = browser_runtime, nss_material
    (root / "inventory.json").write_text(json.dumps({"version": 2, "issued_identities": []}))
    if not pk12_available:
        which = shutil.which
        monkeypatch.setattr(runtime.shutil, "which", lambda name: None if name == "pk12util" else which(name))
    runtime.main()
    for database in (*runtime.nss_databases(), runtime.STATE / "firefox/all"):
        assert list(nss_listing(database).values()) == ["CT,c,c", "CT,c,c"]
        assert_server_trust(root, database, "original", True)
        assert_server_trust(root, database, "intercepted", True)


def test_firefox_identity_profile_includes_selected_trust(
    nss_material: Path, browser_runtime: ModuleType,
) -> None:
    runtime, root = browser_runtime, nss_material
    leaves = json.loads((root / "inventory.json").read_text())["issued_identities"]
    profile = runtime.firefox_profile(root, leaves, "local/secondary")
    assert nss_listing(profile)["local/secondary"] == "u,u,u"
    assert "local/client" not in nss_listing(profile)
    assert_server_trust(root, profile, "original", True)
    assert_server_trust(root, profile, "intercepted", True)
    assert_server_trust(root, profile, "unselected", False)


def test_trust_reselection_and_empty_bundle_clear_only_owned_trust(
    nss_material: Path, browser_runtime: ModuleType,
) -> None:
    runtime, root = browser_runtime, nss_material
    runtime.main()
    database = runtime.STATE / "firefox/all"
    run_tool(
        "certutil", "-A", "-d", f"sql:{database}", "-n", "operator-ca", "-t", "CT,c,c", "-a",
        "-i", str(root / "unrelated/certificate.pem"),
    )
    bundle = root / "trust/ca-bundle.pem"
    bundle.write_text((root / "issuing/certificate.pem").read_text())
    runtime.main()
    assert_server_trust(root, database, "original", True)
    assert_server_trust(root, database, "intercepted", False)
    bundle.write_text("")
    runtime.main()
    assert_server_trust(root, database, "original", False)
    listing = nss_listing(database)
    assert listing["operator-ca"] == "CT,c,c"
    assert listing["local/client"] == listing["local/secondary"] == "u,u,u"
    assert [name for name, flags in listing.items() if "C" in flags] == ["operator-ca"]


def test_failed_trust_import_is_reconciled_after_selection_changes(
    nss_material: Path, browser_runtime: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, root = browser_runtime, nss_material
    database = runtime.STATE / "firefox/all"
    run = subprocess.run
    imports = 0

    def fail_second_import(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        nonlocal imports
        if args[:2] == ["certutil", "-A"]:
            imports += 1
            if imports == 2:
                raise subprocess.CalledProcessError(1, args)
        return run(args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(runtime.subprocess, "run", fail_second_import)
        with pytest.raises(subprocess.CalledProcessError):
            runtime.nss_trust(root, database)
    assert_server_trust(root, database, "intercepted", True)
    (root / "trust/ca-bundle.pem").write_text((root / "issuing/certificate.pem").read_text())
    runtime.nss_trust(root, database)
    assert_server_trust(root, database, "intercepted", False)
    assert_server_trust(root, database, "original", True)


@pytest.mark.parametrize("contents", [
    "not PEM", "-----BEGIN CERTIFICATE-----\nmissing end",
    "-----BEGIN CERTIFICATE-----\n!!!\n-----END CERTIFICATE-----\n",
])
def test_nss_rejects_malformed_bundle_before_importing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str,
) -> None:
    runtime = load_runtime()
    bundle = tmp_path / "trust/ca-bundle.pem"
    bundle.parent.mkdir()
    bundle.write_text(contents)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: f"/test/{name}")
    with pytest.raises(RuntimeError, match="invalid PEM certificate bundle"):
        runtime.nss_trust(tmp_path, tmp_path / "nssdb")
    assert not (tmp_path / "nssdb").exists()


CHROMIUM = ("chromium", "chromium-browser", "google-chrome")
FIREFOX = ("firefox", "firefox-esr")
# The browser fixture makes the runtime detect browsers that need not be
# installed, so locating a real binary has to bypass that patched lookup.
WHICH = shutil.which


def installed(*names: str) -> str | None:
    return next((path for name in names if (path := WHICH(name))), None)


@pytest.fixture
def chromium_binary() -> str:
    binary = installed(*CHROMIUM)
    if binary is None:
        pytest.skip("real browser trust tests require Chrome or Chromium")
    return binary


@pytest.fixture
def firefox_binary() -> str:
    binary = installed(*FIREFOX)
    if binary is None:
        pytest.skip("real browser trust tests require Firefox")
    return binary


def render(command: list[str], environment: dict[str, str]) -> str:
    # A browser that neither loads nor gives up is a failure of the trust the
    # database carries, not an error in the harness that started it.
    try:
        return subprocess.run(
            command, env=os.environ | environment,
            capture_output=True, text=True, check=False, timeout=180,
        ).stdout
    except subprocess.TimeoutExpired:
        return ""


@contextlib.contextmanager
def https_origin(root: Path, name: str) -> Iterator[int]:
    """Serve the named leaf certificate on a loopback port.

    Every selected anchor signs its leaf directly, so the leaf alone completes
    the chain a browser has to build out of the database under test.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / name / "certificate.pem", root / name / "private-key.pem")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"<html><body>eclab-pki trust probe</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # A browser that distrusts the chain aborts mid-handshake; that is the
    # outcome under test, not a server fault worth a traceback.
    server.handle_error = lambda *args: None  # type: ignore[method-assign]
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=30)


def chromium_loads(binary: str, home: Path, port: int) -> bool:
    return "eclab-pki trust probe" in render(
        [binary, "--headless", "--no-sandbox", "--disable-gpu", "--no-first-run",
         f"--user-data-dir={home / 'chromium-data'}", "--virtual-time-budget=5000",
         "--dump-dom", f"https://127.0.0.1:{port}/"],
        {"HOME": str(home)},
    )


def firefox_loads(binary: str, home: Path, profile: Path, port: int) -> bool:
    # Firefox renders its interstitial without ever firing a load event, so a
    # screenshot only appears when it accepted the chain.
    screenshot = home / f"probe-{port}.png"
    render(
        [binary, "--headless", "--no-remote", "--profile", str(profile),
         "--screenshot", str(screenshot), f"https://127.0.0.1:{port}/"],
        {"HOME": str(home), "MOZ_HEADLESS": "1"},
    )
    return screenshot.is_file() and screenshot.stat().st_size > 0


@pytest.mark.parametrize("chain", ["original", "intercepted"])
def test_chromium_accepts_selected_chains_from_the_managed_database(
    nss_material: Path, browser_runtime: ModuleType, chromium_binary: str, chain: str,
) -> None:
    runtime, root = browser_runtime, nss_material
    runtime.main()

    with https_origin(root, chain) as port:
        assert chromium_loads(chromium_binary, runtime.Path.home(), port)


def test_chromium_accepts_selected_chains_from_the_fallback_database(
    nss_material: Path, browser_runtime: ModuleType, chromium_binary: str,
) -> None:
    runtime, root = browser_runtime, nss_material
    runtime.main()
    home = runtime.Path.home()
    # Builds that read only the XDG data directory see exactly this layout, and
    # a node whose trust reached ~/.pki/nssdb alone would fail the chain here.
    shutil.rmtree(home / ".pki")

    with https_origin(root, "original") as port:
        assert chromium_loads(chromium_binary, home, port)


@pytest.mark.parametrize("chain", ["original", "intercepted"])
def test_firefox_accepts_selected_chains_from_the_managed_profile(
    nss_material: Path, browser_runtime: ModuleType, firefox_binary: str, chain: str,
) -> None:
    runtime, root = browser_runtime, nss_material
    runtime.main()

    with https_origin(root, chain) as port:
        assert firefox_loads(firefox_binary, runtime.Path.home(), runtime.STATE / "firefox/all", port)
