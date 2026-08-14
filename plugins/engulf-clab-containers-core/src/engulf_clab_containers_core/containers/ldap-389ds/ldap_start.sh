#!/bin/sh
# Boots one 389 Directory Server instance plus Cockpit (389-console focus) in
# a non-systemd container: creates the instance on first run, creates the
# suffix backend, enables the MemberOf plugin, restarts, seeds entries from
# /etc/dirsrv/seed.ldif, then starts DBus/polkit/Cockpit.
#
# Environment overrides (baked-in defaults suit a generic lab):
#
#   LDAP_INSTANCE         389 DS instance name (slapd-<name>).
#   LDAP_BASE_DN          suffix to create and serve.
#   LDAP_DM_DN            directory manager bind DN.
#   LDAP_DM_PASSWORD      directory manager password; also the bind password
#                         seeded entries typically reference.
#   LDAP_SEED_LDIF        LDIF applied on first run.
#   COCKPIT_ADMIN_USER    local Linux user allowed to log into Cockpit.
#   COCKPIT_ADMIN_PASSWORD  password for that user.
set -eu

: "${LDAP_INSTANCE:=localhost}"
: "${LDAP_BASE_DN:=dc=lab,dc=local}"
: "${LDAP_DM_DN:=cn=Directory Manager}"
: "${LDAP_DM_PASSWORD:=admin123}"
: "${LDAP_SEED_LDIF:=/etc/dirsrv/seed.ldif}"
: "${COCKPIT_ADMIN_USER:=admin}"
: "${COCKPIT_ADMIN_PASSWORD:=admin}"

wait_for_local_ldap() {
    tries=0
    until ldapsearch -x -H ldap://127.0.0.1:389 -b "" -s base namingContexts >/dev/null 2>&1; do
        tries=$((tries + 1))
        [ "$tries" -lt 60 ] || { echo "local LDAP did not become ready" >&2; return 1; }
        sleep 1
    done
}

start_directory() {
    mkdir -p /run/dirsrv
    dsctl "$LDAP_INSTANCE" start || true
    if ! ldapsearch -x -H ldap://127.0.0.1:389 -b "" -s base namingContexts >/dev/null 2>&1; then
        /usr/sbin/ns-slapd -D "/etc/dirsrv/slapd-${LDAP_INSTANCE}" \
            -i "/run/dirsrv/slapd-${LDAP_INSTANCE}.pid" &
    fi
    wait_for_local_ldap
}

initialize_directory() {
    # Derive a FQDN for the instance from the suffix: dc=lab,dc=local ->
    # ldap.lab.local. Non-dc suffixes fall back to ldap.lab.local.
    base_dc="$(printf '%s' "$LDAP_BASE_DN" | tr -d ' ' | sed -n 's/^\(dc=[^,]*\)\(.*\)/\1\2/p' | sed 's/,[dD][cC]=/./g; s/^[dD][cC]=//' | tr 'A-Z' 'a-z')"
    full_machine_name="ldap.${base_dc:-lab.local}"
    cat >/tmp/dscreate.inf <<EOF
[general]
full_machine_name = ${full_machine_name}
strict_host_checking = false
selinux = false

[slapd]
instance_name = ${LDAP_INSTANCE}
root_dn = ${LDAP_DM_DN}
root_password = ${LDAP_DM_PASSWORD}
port = 389
secure_port = 636
self_sign_cert = false
EOF
    dscreate from-file /tmp/dscreate.inf
    start_directory
    dsconf "$LDAP_INSTANCE" backend create --suffix "$LDAP_BASE_DN" --be-name userroot
    dsconf "$LDAP_INSTANCE" plugin memberof enable
    dsctl "$LDAP_INSTANCE" restart
    wait_for_local_ldap
    # The just-created suffix backend is an empty database: its root entry
    # (the base DN) does not exist until something adds it. Seed entries under
    # the suffix fail with "No such object" (ldap error 32) unless the seed
    # creates the root first, so synthesize it from LDAP_BASE_DN.
    {
        printf 'dn: %s\n' "$LDAP_BASE_DN"
        # dc is single-valued; the root entry's RDN carries only the first
        # component even though the DN has several.
        first_dc="$(printf '%s' "$LDAP_BASE_DN" | tr -d ' ' | sed -n 's/^[dD][cC]=\([^,]*\).*/\1/p')"
        printf 'dc: %s\n' "${first_dc:-ldap}"
        printf 'objectClass: top\nobjectClass: domain\n\n'
        cat "$LDAP_SEED_LDIF"
    } >/tmp/seed-with-root.ldif
    if ! ldapadd -c -x -H ldap://127.0.0.1:389 -D "$LDAP_DM_DN" -w "$LDAP_DM_PASSWORD" \
        -f /tmp/seed-with-root.ldif; then
        echo "ldapadd reported seed errors; see output above" >&2
    fi
}

ensure_cockpit_user() {
    id "$COCKPIT_ADMIN_USER" >/dev/null 2>&1 || useradd -m -G wheel "$COCKPIT_ADMIN_USER"
    printf '%s:%s\n' "$COCKPIT_ADMIN_USER" "$COCKPIT_ADMIN_PASSWORD" | chpasswd
    mkdir -p /etc/sudoers.d
    printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$COCKPIT_ADMIN_USER" >/etc/sudoers.d/99-cockpit-admin
    chmod 440 /etc/sudoers.d/99-cockpit-admin
}

start_services() {
    mkdir -p /run/dbus /run/cockpit
    dbus-daemon --system --fork --nopidfile
    /usr/lib/polkit-1/polkitd --no-debug >/tmp/polkit.log 2>&1 &
    cat >/tmp/cockpit_session.py <<'PY'
import grp
import os
import socket
import subprocess
import threading

path = "/run/cockpit/session"


def handle(conn):
    source = os.fdopen(os.dup(conn.fileno()), "rb", buffering=0)
    sink = os.fdopen(os.dup(conn.fileno()), "wb", buffering=0)
    subprocess.run(["/usr/libexec/cockpit-session"], stdin=source, stdout=sink,
                   stderr=subprocess.DEVNULL, check=False)
    conn.close()


try:
    os.unlink(path)
except FileNotFoundError:
    pass
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path)
try:
    os.chown(path, 0, grp.getgrnam("cockpit-session-socket").gr_gid)
except KeyError:
    pass
os.chmod(path, 0o660)
server.listen(32)
while True:
    client, _ = server.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
PY
    python3 /tmp/cockpit_session.py &
    # Hide modules that assume a full systemd host; retain the 389 console.
    mkdir -p /usr/share/cockpit-disabled
    for module in apps metrics packagekit systemd users; do
        [ ! -d "/usr/share/cockpit/$module" ] || mv "/usr/share/cockpit/$module" /usr/share/cockpit-disabled/
    done
    if [ -x /usr/libexec/cockpit-ws ]; then
        /usr/libexec/cockpit-ws --no-tls --port 9090 --address 0.0.0.0 &
    else
        cockpit-ws --no-tls --port 9090 --address 0.0.0.0 &
    fi
}

ensure_cockpit_user
if [ ! -d "/etc/dirsrv/slapd-${LDAP_INSTANCE}" ]; then
    initialize_directory
else
    start_directory
fi
start_services
echo "ldap-start: services launched; streaming directory errors log" >&2
mkdir -p "/var/log/dirsrv/slapd-${LDAP_INSTANCE}"
touch "/var/log/dirsrv/slapd-${LDAP_INSTANCE}/errors"
# exec so tail replaces this script as PID 1: ns-slapd and cockpit-ws are
# daemon children, and the container's lifetime is the directory log stream.
exec tail -F "/var/log/dirsrv/slapd-${LDAP_INSTANCE}/errors"
