FROM fedora:44

RUN dnf install -y curl iproute && dnf clean all
COPY --from=engulf-clab.pki-linux-fedora/installer:latest /opt/eclab-pki /opt/eclab-pki
RUN /opt/eclab-pki/install

ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--"]
CMD ["sleep", "infinity"]
