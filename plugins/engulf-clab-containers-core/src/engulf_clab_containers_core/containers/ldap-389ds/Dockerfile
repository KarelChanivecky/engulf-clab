FROM fedora:latest

RUN dnf -y install \
        389-ds-base \
        bind-utils \
        cockpit \
        cockpit-389-ds \
        dbus-daemon \
        iproute \
        iputils \
        openldap-clients \
        openssl \
        passwd \
        polkit \
        procps-ng \
        python3 \
        sudo \
        tcpdump \
    && dnf clean all \
    && rm -rf /var/cache/dnf

COPY containers/ldap-389ds/ldap_start.sh /usr/local/bin/ldap-start
COPY containers/ldap-389ds/seed.ldif /etc/dirsrv/seed.ldif

RUN chmod 0755 /usr/local/bin/ldap-start

# 389/636 = directory (keep on the appliance-facing data plane; do not
# publish to the host unless a lab explicitly requires it), 9090 = Cockpit.
EXPOSE 389 636 9090

ENTRYPOINT ["/usr/local/bin/ldap-start"]
