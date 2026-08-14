#!/bin/sh
# Starts the proxy control UI, Squid, and Dante in one container. Fix Squid
# log ownership, tail all daemon logs to the container log, and reload Squid
# whenever proxy_control.py rewrites /etc/squid/squid.conf.
#
# Dante starts in a background path so a slow data plane never blocks the
# working Squid HTTP proxy. Two optional environment variables gate it:
#
#   SOCKS_EXTERNAL_IP   IP address the lab assigns to this node's data-plane
#                       interface (must equal `external` in /etc/sockd.conf).
#                       Dante waits until the address exists on an interface.
#   SOCKS_WAIT_DNS      Lab nameserver IP. When set, Dante additionally waits
#                       until /etc/resolv.conf lists it and a test lookup
#                       succeeds, so early browser traffic does not fail with
#                       temporary hostname errors.
#
# Both waits time out and start Dante anyway rather than wedge SOCKS forever.
set -eu

log_tail() {
    tail -F "$1" 2>/dev/null &
}

ui_pid=
squid_pid=
dante_pid=

stop_children() {
    for pid in "$ui_pid" "$squid_pid" "$dante_pid"; do
        [ -n "$pid" ] || continue
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}

wait_for_egress_ip() {
    [ -n "${SOCKS_EXTERNAL_IP:-}" ] || return 0
    match="$(printf '%s' "$SOCKS_EXTERNAL_IP" | sed 's/[.]/[.]/g')/"
    i=0
    until ip -4 addr show | grep -q "$match"; do
        i=$((i + 1))
        if [ "$i" -ge 120 ]; then
            echo "Timed out waiting for data-plane IP ${SOCKS_EXTERNAL_IP}; starting Dante anyway" >&2
            return 0
        fi
        sleep 1
    done
}

wait_for_dns() {
    [ -n "${SOCKS_WAIT_DNS:-}" ] || return 0
    i=0
    until grep -q "^nameserver ${SOCKS_WAIT_DNS}\$" /etc/resolv.conf \
        && dig +time=1 +tries=1 +short "@${SOCKS_WAIT_DNS}" detectportal.firefox.com A >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -ge 300 ]; then
            echo "Timed out waiting for DNS at ${SOCKS_WAIT_DNS}; starting Dante anyway" >&2
            return 0
        fi
        sleep 1
    done
}

mkdir -p /var/log/squid /var/spool/squid /run
touch /var/log/squid/access.log /var/log/squid/error.log /var/log/squid/store.log /var/log/squid/cache.log
touch /var/log/sockd.log
chown -R proxy:proxy /var/log/squid /var/spool/squid

log_tail /var/log/squid/access.log
log_tail /var/log/squid/error.log
log_tail /var/log/squid/store.log
log_tail /var/log/squid/cache.log
log_tail /var/log/sockd.log

python3 /opt/proxy_control.py &
ui_pid=$!

sleep 1
/usr/sbin/squid -Nz || true
/usr/sbin/squid -f /etc/squid/squid.conf -NYC &
squid_pid=$!

(
    wait_for_egress_ip
    wait_for_dns
    exec /usr/sbin/danted -f /etc/sockd.conf
) &
dante_pid=$!

last_mtime="$(stat -c %Y /etc/squid/squid.conf 2>/dev/null || echo 0)"

trap stop_children INT TERM

while kill -0 "$squid_pid" 2>/dev/null; do
    current_mtime="$(stat -c %Y /etc/squid/squid.conf 2>/dev/null || echo 0)"
    if [ "$current_mtime" != "$last_mtime" ]; then
        last_mtime="$current_mtime"
        /usr/sbin/squid -f /etc/squid/squid.conf -k reconfigure || true
    fi
    sleep 2
done

stop_children
