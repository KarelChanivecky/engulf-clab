FROM debian:13

RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium curl firefox-esr iproute2 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=engulf-clab.pki-linux-debian/installer:latest /opt/eclab-pki /opt/eclab-pki
RUN /opt/eclab-pki/install

ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--"]
CMD ["sleep", "infinity"]
