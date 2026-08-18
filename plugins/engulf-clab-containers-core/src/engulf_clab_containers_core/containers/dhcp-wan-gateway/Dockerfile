FROM alpine:3.24

RUN apk add --no-cache iproute2 iptables python3 dnsmasq

COPY wan_gateway_runtime.py /usr/local/lib/eclab-dhcp-wan-gateway.py

HEALTHCHECK --interval=5s --timeout=2s --retries=12 CMD test -f /run/eclab-dhcp-wan-gateway.ready
ENTRYPOINT ["python3", "/usr/local/lib/eclab-dhcp-wan-gateway.py"]
