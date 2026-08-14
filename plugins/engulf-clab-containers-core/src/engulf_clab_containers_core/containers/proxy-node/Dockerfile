# Browser-access proxy node for eclab-managed labs: Squid HTTP/HTTPS forward
# proxy, Dante SOCKS5 proxy, and a small control UI. Labs override the baked-in
# defaults with bind mounts; see README.md.
FROM ubuntu/squid:latest

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bind9-dnsutils \
        curl \
        dante-server \
        iproute2 \
        iputils-ping \
        net-tools \
        procps \
        python3 \
        squidclient \
        tcpdump \
        traceroute \
    && rm -rf /var/lib/apt/lists/*

COPY containers/proxy-node/squid.conf /etc/squid/squid.conf
COPY containers/proxy-node/sockd.conf /etc/sockd.conf
COPY containers/proxy-node/proxy_control.py /opt/proxy_control.py
COPY containers/proxy-node/proxy-control.json /etc/squid/proxy-control.json
COPY containers/proxy-node/proxy_start.sh /usr/local/bin/entrypoint.sh

RUN chmod 0755 /usr/local/bin/entrypoint.sh

EXPOSE 8888 1080 8890

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
