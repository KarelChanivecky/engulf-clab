# Fedora-family installation

```dockerfile
COPY --from=engulf-clab.pki-linux-fedora/installer:latest /opt/eclab-pki /opt/eclab-pki
RUN /opt/eclab-pki/install
ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--", "/original-entrypoint"]
```

The build installs Python, OpenSSL, CA-store, and NSS certificate-management prerequisites,
never target applications. Runtime detection remains authoritative. Fedora 44 is the primary
target.
