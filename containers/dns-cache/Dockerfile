FROM python:3.12-slim

RUN pip install --no-cache-dir dnslib==0.9.26

COPY dns_cache_runtime.py /usr/local/lib/eclab-dns-cache.py

RUN mkdir -p /var/lib/eclab-dns-cache

EXPOSE 53/udp 53/tcp
HEALTHCHECK --interval=10s --timeout=2s --retries=3 CMD python3 -c 'import socket; s=socket.create_connection(("127.0.0.1",53),timeout=1); s.close()'
ENTRYPOINT ["python3", "/usr/local/lib/eclab-dns-cache.py"]
