FROM eclab.containers.pki/debian:latest
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl iproute2 iputils-ping openssh-client sshpass python3-cryptography && \
    rm -rf /var/lib/apt/lists/*
COPY marker /roundtrip-base
LABEL org.engulf.freeze-roundtrip.base="base-v1"
