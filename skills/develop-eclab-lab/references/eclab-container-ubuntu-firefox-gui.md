# eclab.containers/ubuntu-firefox-gui

Reusable Containerlab Linux client image with:

- Ubuntu 24.04
- XFCE desktop
- Firefox from Mozilla's APT repository
- default Firefox profile with first-run/welcome prompts disabled
- Firefox enterprise policy disabling default-browser checks and onboarding
- optional NSS DB import for mounted lab CA/client certificates
- noVNC on TCP `6080`
- x11vnc bound internally to `127.0.0.1:5900`
- common network tools: `curl`, `iproute2`, `iputils-ping`, `net-tools`

The image does not include Squid, Dante, custom proxy control software, lab
certificates, static routes, static IP addresses, or browser proxy settings.
Those belong in the consuming lab topology and documentation. When a lab
needs an explicit proxy, pair this client with the `eclab.containers/proxy-node` image.

## Firefox Defaults

`firefox-user.js` seeds the default Firefox profile with:

```js
user_pref("trailhead.firstrun.didSeeAboutWelcome", true);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
```

`firefox-policies.json` installs to
`/usr/lib/firefox/distribution/policies.json` and disables default-browser
checks and onboarding:

```json
{
  "policies": {
    "DontCheckDefaultBrowser": true,
    "UserMessaging": {
      "SkipOnboarding": true
    }
  }
}
```

The desktop launcher starts Firefox with
`--profile /home/ubuntu/.mozilla/firefox/default` so Firefox uses the profile
that receives the seeded preferences and any startup certificate imports.

## Proxy Policy

When a consuming lab wants Firefox traffic proxied, infer the settings from
that lab's topology and appliance configs and provide a per-lab Firefox policy
override. Prefer PAC files over static manual proxy settings for both plain
and secure proxies. PAC makes the proxy transport explicit (`PROXY`, `HTTPS`,
`SOCKS`, or `DIRECT`) and avoids ambiguity around secure explicit proxies. Do
not lock the proxy policy; users must still be able to override proxy settings
interactively in Firefox.

Recommended policy:

```json
{
  "policies": {
    "DontCheckDefaultBrowser": true,
    "UserMessaging": {
      "SkipOnboarding": true
    },
    "Proxy": {
      "Mode": "autoConfig",
      "Locked": false,
      "AutoConfigURL": "file:///usr/lib/firefox/distribution/proxy.pac"
    }
  }
}
```

Example PAC for a secure explicit proxy:

```js
function FindProxyForURL(url, host) {
    if (isPlainHostName(host) || shExpMatch(host, "localhost") || isInNet(host, "127.0.0.0", "255.0.0.0")) {
        return "DIRECT";
    }

    return "HTTPS proxy.lab.test:8443";
}
```

Example PAC for a plain HTTP proxy:

```js
function FindProxyForURL(url, host) {
    if (isPlainHostName(host) || shExpMatch(host, "localhost") || isInNet(host, "127.0.0.0", "255.0.0.0")) {
        return "DIRECT";
    }

    return "PROXY proxy.lab.test:8080";
}
```

For secure explicit proxies, use the proxy certificate hostname rather than a
raw IP address.

Static manual proxy policy is a fallback only. If a lab specifically requires
manual settings, it can be expressed like:

```json
{
  "policies": {
    "Proxy": {
      "Mode": "manual",
      "Locked": false,
      "HTTPProxy": "proxy.lab.test:8080",
      "UseHTTPProxyForAllProtocols": true,
      "SSLProxy": "proxy.lab.test:8080",
      "Passthrough": "<local>"
    }
  }
}
```

Use SOCKS settings only when the lab provides a SOCKS proxy. For SOCKS5
DNS-through-proxy tests, set `SOCKSProxy`, `SOCKSVersion: 5`, and
`UseProxyForDNS: true` in the PAC return value and/or Firefox policy as needed
for that lab.

## Certificate Import

At startup, `gui-start.sh` creates a Firefox NSS DB for the default profile
and imports lab certificates when the files are present:

- `FIREFOX_CA_CERT`, default `/home/ubuntu/certs/ca.crt`
- `FIREFOX_CLIENT_P12`, default `/home/ubuntu/certs/client.p12`
- `FIREFOX_CLIENT_P12_PASSWORD`, default empty
- `FIREFOX_CA_NICKNAME`, default `Lab CA`

For a lab with a client certificate, mount the certificate directory
read-only and, only if the PKCS#12 file has a password, set it on the node:

```yaml
client:
  kind: linux
  image: eclab.containers/ubuntu-firefox-gui
  env:
    FIREFOX_CLIENT_P12_PASSWORD: <p12-password>
  binds:
    - certs:/home/ubuntu/certs:ro
```

For passwordless lab PKCS#12 files, omit `FIREFOX_CLIENT_P12_PASSWORD`.
If users need to browse to or manually import the mounted PKCS#12 file from
the desktop, make the host file readable by the container user, for example
`chmod 0644 certs/client.p12`. The startup importer can stage restrictive
files when root can read the bind mount, but the Firefox file picker runs as
the `ubuntu` desktop user.

If Firefox has already created an additional `*.default-release` profile, the
startup importer also imports the mounted certificates there so the client
certificate appears under Firefox's "Your Certificates" view for that
profile.

## Build

Built as `eclab.containers/ubuntu-firefox-gui:latest` during `eclab deploy`. To build
directly, use the package as the build context:

```bash
docker build --tag eclab.containers/ubuntu-firefox-gui:latest \
  -f src/engulf_clab_containers_core/containers/ubuntu-firefox-gui/Dockerfile src/engulf_clab_containers_core
```


## Containerlab Usage

```yaml
client:
  kind: linux
  image: eclab.containers/ubuntu-firefox-gui
  ports:
    - 127.0.0.1:6080:6080
  exec:
    - ip addr add 10.10.10.10/24 dev eth1
    - ip link set eth1 up
    - ip route replace default via 10.10.10.1 dev eth1
```

Open the desktop at:

```text
http://127.0.0.1:6080/vnc.html?autoconnect=1
```

Override the virtual display size with `GUI_RESOLUTION`, for example
`1920x1080x24`.
