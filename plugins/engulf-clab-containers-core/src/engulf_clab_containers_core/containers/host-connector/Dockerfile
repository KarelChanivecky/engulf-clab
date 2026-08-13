FROM alpine:3.24

RUN apk add --no-cache iproute2 iptables python3

COPY runtime.py /usr/local/lib/eclab-host-connector.py

HEALTHCHECK --interval=5s --timeout=2s --retries=12 CMD test -f /run/eclab-host-connector.ready
ENTRYPOINT ["python3", "/usr/local/lib/eclab-host-connector.py"]
