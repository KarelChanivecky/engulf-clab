#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:0}"
export HOME=/home/ubuntu
export USER=ubuntu

install -d -o ubuntu -g ubuntu /home/ubuntu/.config /home/ubuntu/.cache
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0

firefox_profile="${FIREFOX_PROFILE_DIR:-/home/ubuntu/.mozilla/firefox/default}"
firefox_ca_cert="${FIREFOX_CA_CERT:-/home/ubuntu/certs/ca.crt}"
firefox_client_p12="${FIREFOX_CLIENT_P12:-/home/ubuntu/certs/client.p12}"
firefox_client_p12_password="${FIREFOX_CLIENT_P12_PASSWORD:-}"

import_firefox_certs() {
    local profile="$1"
    local firefox_nssdb="sql:${profile}"
    local staged_client_p12

    install -d -o ubuntu -g ubuntu "$profile"
    sudo -Eu ubuntu certutil -N -d "$firefox_nssdb" --empty-password >/dev/null 2>&1 || true

    if [[ -r "$firefox_ca_cert" ]]; then
        sudo -Eu ubuntu certutil -A -d "$firefox_nssdb" \
            -n "${FIREFOX_CA_NICKNAME:-Lab CA}" \
            -t "CT,c,c" \
            -i "$firefox_ca_cert" \
            >/dev/null 2>&1 || true
    fi

    if [[ -r "$firefox_client_p12" ]]; then
        staged_client_p12="$(mktemp /tmp/firefox-client-p12.XXXXXX)"
        cp "$firefox_client_p12" "$staged_client_p12"
        chown ubuntu:ubuntu "$staged_client_p12"
        chmod 0600 "$staged_client_p12"
        sudo -Eu ubuntu pk12util -i "$staged_client_p12" \
            -d "$firefox_nssdb" \
            -W "$firefox_client_p12_password" \
            -K "" \
            >/dev/null 2>&1 || true
        rm -f "$staged_client_p12"
    fi
}

import_firefox_certs "$firefox_profile"
for existing_profile in /home/ubuntu/.mozilla/firefox/*.default /home/ubuntu/.mozilla/firefox/*.default-release; do
    [[ -d "$existing_profile" && "$existing_profile" != "$firefox_profile" ]] || continue
    import_firefox_certs "$existing_profile"
done
chown -R ubuntu:ubuntu /home/ubuntu/.mozilla

Xvfb "$DISPLAY" -screen 0 "${GUI_RESOLUTION:-1440x900x24}" -ac +extension GLX +render -noreset &

for _ in $(seq 1 50); do
    xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break
    sleep 0.1
done

sudo -Eu ubuntu dbus-launch --exit-with-session startxfce4 &
x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport 5900 -listen 127.0.0.1 &

exec websockify --web=/usr/share/novnc/ 0.0.0.0:6080 127.0.0.1:5900
