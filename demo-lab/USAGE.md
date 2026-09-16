# Portable demo-lab usage

## Install

Install with Python 3.12 or newer. The distribution installs eclab and the
curated plugin set required by the lab; it deliberately excludes proprietary
vrnetlab, license-pool, managed-WAN, and generated-skill features.

```bash
python3.12 -m pip install engulf-clab-demo-lab
eclab-demo-lab-install
```

The destination defaults to `./eclab-demo-lab`. Use `--check` for read-only
verification. A changed recognized installation is replaced only with
`--replace`, after it is moved to the selected backup directory. Unrecognized
and symlinked targets are always refused.

## Operate

The installed `RUNBOOK.md` is the complete workflow. In outline:

```bash
cd eclab-demo-lab
./prepare-archive.sh
./run-eclab.sh pki effective -t lab.clab.yaml
./run-eclab.sh deploy -t lab.clab.yaml
./run-eclab.sh inspect --name eclab-all-features
./run-eclab.sh destroy -t lab.clab.yaml
./run-eclab.sh freeze -t lab.clab.yaml --offline --output demo.tar.gz
```

Inspect by lab name because the source contains build-only nodes that are
intentionally absent from the deployed topology.

Deployment needs Docker access and the privileges required by Containerlab. It
can pull the public images named by the topology and PKI service recipes. The
two internal L2 networks are bridges inside the `segments` container namespace,
so no pre-created host bridge is needed. A small Linux router forwards between
the client and DMZ subnets and uses the packaged `wan-access` node as an uplink.

The Debian and Fedora consumers inherit the matching base from the PKI-scoped
container collection and retain its trust-bootstrap entrypoint. Client A
demonstrates multiple identities, curl selection, Chromium origin policy,
Firefox NSS discovery, and a Playwright descriptor. Debian nginx requires a
generated client certificate directly; Fedora nginx serves a cross-signed
chain. See `RUNBOOK.md` for positive and negative checks.

## Security and cleanup

The package contains no credential, certificate, key, passphrase, VM image, or
license. The database recipe requests a runtime-generated root password; that
value is not lab source. Generated Docker archives and PKI state are ignored.
Review the topology, Dockerfiles, and scripts before deployment. Use successful
`destroy` for normal PKI-view cleanup.

Offline freeze produces a self-contained sharing artifact from public container
images. Optional private PKI export still requires an owner-private passphrase
file, which must remain outside the lab.
