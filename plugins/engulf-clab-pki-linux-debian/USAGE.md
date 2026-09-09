# Debian-family installation

```dockerfile
COPY --from=engulf-clab.pki-linux-debian/installer:latest /opt/eclab-pki /opt/eclab-pki
RUN /opt/eclab-pki/install
ENTRYPOINT ["/opt/eclab-pki/entrypoint", "--", "/original-entrypoint"]
```

The build installs Python, OpenSSL, CA-store, and NSS certificate-management prerequisites;
it does not install browsers, clients, or servers. Application detection is recorded at build
time and repeated authoritatively at every startup. Debian 13 is the primary target.
