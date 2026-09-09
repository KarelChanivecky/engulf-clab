FROM debian:13

RUN apt-get update && \
    apt-get install -y --no-install-recommends iproute2 nginx && \
    rm -rf /var/lib/apt/lists/*
COPY --from=engulf-clab.pki-linux-debian/installer:latest /opt/eclab-pki /opt/eclab-pki
RUN /opt/eclab-pki/install && rm -f /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/conf.d/eclab-demo.conf

ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--"]
CMD ["nginx", "-g", "daemon off;"]
