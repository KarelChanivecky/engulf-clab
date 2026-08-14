FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:0 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gnupg \
        wget \
    && install -d -m 0755 /etc/apt/keyrings \
    && wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O /etc/apt/keyrings/packages.mozilla.org.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" >/etc/apt/sources.list.d/mozilla.list \
    && { \
        echo "Package: *"; \
        echo "Pin: origin packages.mozilla.org"; \
        echo "Pin-Priority: 1000"; \
    } >/etc/apt/preferences.d/mozilla \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        dbus-x11 \
        firefox \
        fonts-liberation \
        iproute2 \
        iputils-ping \
        libnss3-tools \
        net-tools \
        novnc \
        procps \
        sudo \
        websockify \
        wget \
        x11-utils \
        x11vnc \
        xfce4 \
        xfce4-terminal \
        xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && usermod --home /home/ubuntu --shell /bin/bash ubuntu \
    && install -d -o ubuntu -g ubuntu /home/ubuntu \
    && echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/ubuntu \
    && chmod 0440 /etc/sudoers.d/ubuntu

COPY containers/ubuntu-firefox-gui/gui-start.sh /usr/local/bin/gui-start
COPY containers/ubuntu-firefox-gui/firefox.desktop /home/ubuntu/Desktop/firefox.desktop
COPY containers/ubuntu-firefox-gui/firefox-user.js /home/ubuntu/.mozilla/firefox/default/user.js
COPY containers/ubuntu-firefox-gui/firefox-policies.json /tmp/firefox-policies.json

RUN chmod 0755 /usr/local/bin/gui-start \
    && chmod 0755 /home/ubuntu/Desktop/firefox.desktop \
    && install -d -m 0755 /usr/lib/firefox/distribution \
    && install -m 0644 /tmp/firefox-policies.json /usr/lib/firefox/distribution/policies.json \
    && rm -f /tmp/firefox-policies.json \
    && { \
        echo "[Profile0]"; \
        echo "Name=default"; \
        echo "IsRelative=1"; \
        echo "Path=default"; \
        echo "Default=1"; \
        echo; \
        echo "[General]"; \
        echo "StartWithLastProfile=1"; \
        echo "Version=2"; \
    } >/home/ubuntu/.mozilla/firefox/profiles.ini \
    && chown -R ubuntu:ubuntu /home/ubuntu/Desktop /home/ubuntu/.mozilla

EXPOSE 6080

ENTRYPOINT ["/usr/local/bin/gui-start"]
