# Eclab all-features lab

This directory contains one source topology. The packet path is:

```text
client-net -- fake-wan -- FortiGate -- dmz-net
                    |             `-- work-net
                    `-- real-wan (packaged wan-access container)
```

`client-net`, `dmz-net`, and `work-net` are created inside the `segments`
container namespace. Their topology names contain `|segments` and their
`network-mode` is `container:segments`; a plain bridge would instead require a
pre-existing host bridge.

## 1. Inspect and supply entitled inputs

The installer already recorded the selected FortiGate source in
`local/runtime.env`. It did not copy that file. Check the installation:

```bash
eclab-demo-lab-install --check "$PWD"
```

Place one entitled FortiGate license directly in the empty pool:

```text
inputs/licenses/
```

Do not add a placeholder or metadata file to that directory: every regular
top-level file is a license candidate.

Inspect the active runtime before operating it:

```bash
./run-eclab.sh --engulf-plugin-list
./run-eclab.sh --eclab-containers-help
./run-eclab.sh --help
```

The inventory must not need `engulf_clab.wan` or
`engulf_clab.develop_lab_skill`. Their presence in a shared Python environment
does not activate them because this topology has neither managed-WAN labels nor
the generated-skill command.

## 2. Prepare the ordinary Docker archive

The archive provider needs a real `docker save` stream. Create the disposable
demo archive; this is unrelated to the external FortiGate source:

```bash
./prepare-archive.sh
```

The result is ignored at `artifacts/archive-source.tar.gz`.

## 3. Validate and inspect PKI

Use the exact active generated schema as the validation authority. The package
tests perform this check against the selected runtime. Inspect the effective
PKI graph without generating material:

```bash
./run-eclab.sh pki effective -t all-features.clab.yml
```

The local manifest declares a central CA, certificate database, certificate
directory, CRL responder, OCSP responder, and administration node. The current
generic PKI service contract injects those nodes and their read-only PKI views;
it does not promise production database schema initialization, CRL publication,
or OCSP signing policy.

## 4. Deploy

Deployment builds ordinary Docker images, loads the generated archive, builds
the FortiGate vrnetlab image from the selected external source, allocates the
license, generates PKI, and writes a temporary derived topology:

```bash
./run-eclab.sh deploy -t all-features.clab.yml \
  --eclab-image-build-jobs 2 \
  --eclab-vrnetlab-build-jobs 1
```

The first FortiGate boot and license installation can take several minutes.

## 5. Verify

Check Containerlab state and container health:

```bash
./run-eclab.sh inspect -t all-features.clab.yml
docker ps --filter label=containerlab=eclab-all-features
```

Then verify these paths from the appropriate nodes:

- `client-a` (`10.10.10.10`) through `fake-wan` and FortiGate to
  `dmz-docker` (`192.0.2.10`).
- `client-a` through the same path to `workstation-a` (`198.51.100.10`).
- DMZ and work nodes through FortiGate, `fake-wan`, and `real-wan` to the
  management network's real uplink.
- `real-wan` has exactly `eth0` plus one lab-facing interface and is healthy.
- FortiGate contains the generated public CA objects and its authorized local
  certificate/key pairs.
- `pki-db`, `pki-directory`, `pki-crl`, and `pki-ocsp` exist and received their
  read-only PKI view.

The source `all-features.clab.yml` must still contain only eclab declarations;
generated `FOS_PKI_*` values appear only in the temporary derived topology.

## 6. Destroy

Use normal lifecycle cleanup before freezing or changing the license pool:

```bash
./run-eclab.sh destroy -t all-features.clab.yml
```

Destroy releases the license allocation and removes generated PKI views and the
temporary topology. Built Docker images and persistent PKI history remain.

## 7. Freeze and defrost

Use offline freeze as this demo's sharing path. It deliberately omits the
entitled FortiGate source, so every recipient supplies their own:

```bash
./run-eclab.sh freeze -t all-features.clab.yml --offline --output demo.tar.gz
./run-eclab.sh defrost demo.tar.gz --into restored-demo --no-license-prompt
```

The recipient installs or selects their FortiGate source and places a license
in the restored empty pool before deploy. Optional private PKI export additionally
requires an owner-private passphrase file:

```bash
./run-eclab.sh freeze -t all-features.clab.yml --offline \
  --include-pki-secrets --pki-passphrase-file /private/passphrase-file \
  --output demo-with-pki.tar.gz
```

Never place that passphrase file inside this lab.
