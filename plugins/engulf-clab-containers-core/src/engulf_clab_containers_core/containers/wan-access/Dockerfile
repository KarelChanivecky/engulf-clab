FROM alpine:3.24

RUN apk add --no-cache iproute2 iptables python3 dnsmasq

COPY containers/wan-access/wan_access_runtime.py /usr/local/lib/eclab-wan-access.py

HEALTHCHECK --interval=5s --timeout=2s --retries=12 CMD test -f /run/eclab-wan-access.ready
ENTRYPOINT ["python3", "/usr/local/lib/eclab-wan-access.py"]
