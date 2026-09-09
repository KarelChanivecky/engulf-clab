FROM eclab.containers.pki/debian:latest

RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium curl firefox-esr iproute2 && \
    rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
