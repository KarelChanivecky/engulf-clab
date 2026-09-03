FROM alpine:3.22

ARG DEMO_RELEASE=dev
RUN apk add --no-cache bash curl dnsmasq iproute2 iptables && \
    printf '%s\n' "$DEMO_RELEASE" > /etc/eclab-demo-release
CMD ["sleep", "infinity"]
