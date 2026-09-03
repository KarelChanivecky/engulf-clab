# Comprehensive demo-lab usage

## Install

Install with Python 3.14 or newer. The distribution installs eclab and the
curated plugin set required by the lab; it deliberately excludes
`engulf-clab-wan` and `engulf-clab-develop-eclab-lab`.

```bash
python3.14 -m pip install engulf-clab-demo-lab
eclab-demo-lab-install --fortigate-image /entitled/fortios-v8.0.0.qcow2
```

Interactive installation asks for the same image path. Noninteractive use must
pass `--fortigate-image`. The selected file remains outside the installed lab.
The installer writes only its shell-quoted absolute path to owner-private
`local/runtime.env`.

The destination defaults to `./eclab-demo-lab`. Use `--check` for read-only
verification. A changed recognized installation is replaced only with
`--replace`, after it is moved to the selected backup directory. Unrecognized
and symlinked targets are always refused.

## Operate

The installed `RUNBOOK.md` is the complete workflow. In outline:

```bash
cd eclab-demo-lab
./prepare-archive.sh
./run-eclab.sh pki effective -t all-features.clab.yml
./run-eclab.sh deploy -t all-features.clab.yml
./run-eclab.sh destroy -t all-features.clab.yml
./run-eclab.sh freeze -t all-features.clab.yml --offline --output demo.tar.gz
```

Before deploy, place one entitled FortiGate license file directly inside
`inputs/licenses/`. The directory is intentionally empty after installation.
Deploying the complete topology needs Docker access, QEMU tools, and the
privileges required by Containerlab. It can pull the public images named by the
topology and PKI service recipes.

The three internal L2 networks are bridges inside the `segments` container's
network namespace. Unlike a plain host `kind: bridge`, they need no pre-created
host bridge. Real-WAN access is supplied by the packaged
`eclab.containers/wan-access` node and does not use the excluded managed-WAN
plugin.

## Security and cleanup

The package contains no VM image, license, credential, certificate, key, or
passphrase. The database recipe requests a runtime-generated root password;
that value is not lab source. Generated Docker archives, PKI state, local
runtime selection, and license files are ignored. Review the topology,
Dockerfiles, scripts, and external inputs before deployment. Use successful
`destroy` for normal license and PKI-view cleanup.

Use offline freeze for sharing this demo. It omits entitled vrnetlab VM inputs;
the recipient must select their own image and license. Do not commit a defrosted
directory after resolving private inputs.
