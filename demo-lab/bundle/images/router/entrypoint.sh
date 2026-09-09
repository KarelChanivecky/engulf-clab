#!/bin/sh
set -eu

for interface in eth1 eth2 eth3; do
    attempts=0
    until ip link show "$interface" >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge 120 ]; then
            echo "timed out waiting for $interface" >&2
            exit 1
        fi
        sleep 1
    done
    ip link set "$interface" up
done

ip address replace 10.10.10.1/24 dev eth1
ip address replace 192.0.2.1/24 dev eth2
sysctl -w net.ipv4.ip_forward=1 >/dev/null

udhcpc -i eth3 -q -n

iptables -A FORWARD -i eth1 -o eth2 -j ACCEPT
iptables -A FORWARD -i eth2 -o eth1 -j ACCEPT
iptables -A FORWARD -i eth1 -o eth3 -j ACCEPT
iptables -A FORWARD -i eth2 -o eth3 -j ACCEPT
iptables -A FORWARD -i eth3 -o eth1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -i eth3 -o eth2 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -t nat -A POSTROUTING -o eth3 -j MASQUERADE

exec sleep infinity
