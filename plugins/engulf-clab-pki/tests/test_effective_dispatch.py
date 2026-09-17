"""Exercise inherited requests through installed application dispatch."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
import yaml
from engulf_clab import ContainerlabApp


@pytest.mark.parametrize("level", ["defaults", "kinds", "groups", "nodes"])
def test_pki_effective_dispatch_honors_all_declaration_levels(tmp_path, level):
    manifest = tmp_path / "pki.yaml"
    manifest.write_text(
        "version: 2\nauthorities: {root: {}}\ncertificates: {client-cert: {issuer: root}}\n",
        encoding="utf-8",
    )
    source = {
        "name": "demo",
        "topology": {
            "defaults": {"kind": "linux", "env": {"ECLAB_PKI_MANIFEST": "pki.yaml"}},
            "nodes": {"client": {"group": "clients"}},
        },
    }
    request = {"ECLAB_PKI_CERTIFICATES": "client-cert"}
    if level == "defaults":
        source["topology"]["defaults"]["env"].update(request)
    elif level == "nodes":
        source["topology"]["nodes"]["client"]["env"] = request
    else:
        source["topology"][level] = {"linux" if level == "kinds" else "clients": {"env": request}}
    topology = tmp_path / "lab.clab.yml"
    topology.write_text(yaml.safe_dump(source), encoding="utf-8")
    output = io.StringIO()
    app = ContainerlabApp("/bin/true", state_home_resolver=lambda _: tmp_path / "state")
    with redirect_stdout(output):
        result = app.run(("pki", "effective", "-t", str(topology)))
    assert result == 0
    graph = yaml.safe_load(output.getvalue())
    assert graph["nodes"]["client"]["certificates"][0]["name"] == "local/client-cert"
    assert yaml.safe_load(topology.read_text(encoding="utf-8")) == source
