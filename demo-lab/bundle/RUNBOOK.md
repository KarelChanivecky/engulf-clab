# Eclab portable all-features lab

This directory contains one source topology. Its packet path is:

```text
client-net -- Linux router -- dmz-net
                     |          |-- Debian nginx with direct mTLS
                     |          |-- Fedora nginx with a cross-signed chain
                     |          `-- archive-built HTTP server
                     `-- real-wan (packaged wan-access container)
```

The two internal bridges live in the `segments` container namespace. Their
topology names contain `|segments` and use `network-mode: container:segments`,
so they need no pre-created host bridge.

## 1. Inspect the runtime

Check the installation and inspect the active runtime before operating it:

```bash
eclab-demo-lab-install --check "$PWD"
./run-eclab.sh --engulf-plugin-list
./run-eclab.sh --eclab-containers-help
./run-eclab.sh --help
```

No FortiGate image or license is needed. The inventory deliberately omits the
vrnetlab build, FortiGate PKI injector, and license-pool packages. It also does
not need `engulf_clab.wan` or `engulf_clab.develop_lab_skill`.

## 2. Prepare the Docker archive

The archive provider needs a real `docker save` stream. Create its disposable
input before deploying:

```bash
./prepare-archive.sh
```

The result is ignored at `artifacts/archive-source.tar.gz`.

## 3. Validate and inspect PKI

Use the installed runtime's generated schema as the validation authority. The
package tests perform this check. Inspect the effective PKI graph without
generating material:

```bash
./run-eclab.sh pki effective -t all-features.clab.yml
```

The manifest declares roots, an intermediate and cross-signed variant, TLS
client/server profiles, two client identities, and two nginx identities. It
also declares central CA, database, directory, CRL, OCSP, and administration
service nodes. The generic service contract injects the nodes and read-only PKI
views; it does not promise production service initialization or enforcement.

## 4. Deploy

```bash
./run-eclab.sh deploy -t all-features.clab.yml --eclab-image-build-jobs 2
```

This builds ordinary Docker images, loads the generated archive, creates PKI
material, and writes a temporary derived topology. The source remains unchanged.

## 5. Verify

Inspect by lab name because build-only nodes are absent from the deployed topology:

```bash
./run-eclab.sh inspect --name eclab-all-features
docker ps --filter label=containerlab=eclab-all-features
```

The router should have `10.10.10.1/24` on `eth1`, `192.0.2.1/24` on `eth2`, a
DHCP address on `eth3`, and IPv4 forwarding enabled. Verify routing:

```bash
docker exec clab-eclab-all-features-client-a ping -c 2 192.0.2.10
docker exec clab-eclab-all-features-dmz-docker ping -c 2 10.10.10.10
docker exec clab-eclab-all-features-router ip -brief address
```

`real-wan` should have exactly `eth0` plus one lab-facing interface and report
healthy. PKI service nodes should exist with their read-only PKI views.

### Direct mTLS

Client A owns two identities, but its curl selector chooses `client-a-mtls`.
The curl adapter supplies it to Debian nginx, which validates it against the
generated trust bundle:

```bash
docker exec clab-eclab-all-features-client-a sh -c \
  '. /opt/eclab-pki/state/environment; curl -fsS -D - https://mtls.demo.test/'
```

The response contains `X-Eclab-Client-Certificate: SUCCESS`. Client B trusts
the server chain but has no client identity, so the same origin must reject it:

```bash
! docker exec clab-eclab-all-features-client-b curl -fsS https://mtls.demo.test/
```

### Server identities and cross-signing

Inspect the direct Debian chain and reach the Fedora server's cross-signed chain:

```bash
docker exec clab-eclab-all-features-client-a sh -c \
  '. /opt/eclab-pki/state/environment; openssl s_client -connect dmz.demo.test:443 -servername dmz.demo.test -cert "$ECLAB_PKI_CURL_FULL_CHAIN_FILE" -key "$ECLAB_PKI_CURL_KEY_FILE" </dev/null 2>/dev/null | openssl x509 -noout -issuer -subject'
docker exec clab-eclab-all-features-client-a sh -c \
  '. /opt/eclab-pki/state/environment; curl -fsS https://cross.dmz.demo.test/'
```

The Debian leaf is issued through `issuing -> demo-root`; the Fedora leaf uses
the same issuing key and subject through `issuing/alternate-chain -> alternate-root`.

### Browser identity discovery

Client A's Chromium and Firefox NSS stores contain both `client_auth`
identities. Only the explicit Chromium rule may automatically send
`client-a-mtls`, and only to the exact mTLS origin:

```bash
docker exec clab-eclab-all-features-client-a certutil -L -d sql:/root/.pki/nssdb
docker exec clab-eclab-all-features-client-a certutil -L -d sql:/root/.local/share/pki/nssdb
docker exec clab-eclab-all-features-client-a cat /etc/chromium/policies/managed/eclab-pki.json
docker exec clab-eclab-all-features-client-a cat /opt/eclab-pki/state/playwright-client-certificates.json
docker exec clab-eclab-all-features-client-a /opt/eclab-pki/runtime.py --firefox-profile client-a-mtls
```

## 6. Destroy

```bash
./run-eclab.sh destroy -t all-features.clab.yml
```

Destroy removes generated PKI views and the temporary topology. Built Docker
images and persistent PKI history remain.

## 7. Freeze and defrost

The portable lab can be shared with offline freeze without proprietary inputs:

```bash
./run-eclab.sh freeze -t all-features.clab.yml --offline --output demo.tar.gz
./run-eclab.sh defrost demo.tar.gz --into restored-demo --no-license-prompt
```

Optional private PKI export requires an owner-private passphrase file:

```bash
./run-eclab.sh freeze -t all-features.clab.yml --offline \
  --include-pki-secrets --pki-passphrase-file /private/passphrase-file \
  --output demo-with-pki.tar.gz
```

Never place that passphrase file inside this lab.
