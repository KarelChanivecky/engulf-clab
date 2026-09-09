FROM fedora:44

RUN dnf install -y iproute nginx && dnf clean all
COPY --from=engulf-clab.pki-linux-fedora/installer:latest /opt/eclab-pki /opt/eclab-pki
RUN /opt/eclab-pki/install
COPY nginx.conf /etc/nginx/conf.d/eclab-demo.conf

ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--"]
CMD ["nginx", "-g", "daemon off;"]
