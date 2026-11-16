#!/bin/sh
# The worker never opens a connection of its own, so ffmpeg can't either: the
# container sits on its own bridge, and the host drops anything that subnet
# starts, to the internet, the tailnet or the host itself. Answers to requests
# on the published port still go out. The one way out is Sentry: nginx on the
# host relays the worker's events to it from the bridge's gateway (on licht,
# /etc/nginx/sites-available/remote-sentry-relay), so SENTRY_DSN is
# http://<key>@$GATEWAY:$SENTRY_RELAY_PORT/<project>, and only that port is let
# through, ahead of the drop.
#
# `sandbox.sh network` also creates the Docker network. Without it, this only
# sets the firewall, which is what the host does each time dockerd starts
# (`make install-sandbox`). Safe to run again. Needs root.
set -e

NETWORK=${NETWORK:-remote-sandbox}
SUBNET=172.31.250.0/24
GATEWAY=172.31.250.1
SENTRY_RELAY_PORT=9009

if [ "$1" = network ]; then
	docker network inspect "$NETWORK" >/dev/null 2>&1 \
		|| docker network create --subnet "$SUBNET" --gateway "$GATEWAY" "$NETWORK" >/dev/null
fi

# Docker keeps this chain's rules when it starts, so they can be in place
# before it starts the container.
iptables -N DOCKER-USER 2>/dev/null || true
for chain in DOCKER-USER INPUT; do
	iptables -C "$chain" -s "$SUBNET" -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP 2>/dev/null \
		|| iptables -I "$chain" -s "$SUBNET" -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP
done
# Re-inserted each time, so it always sits above the drop.
iptables -D INPUT -s "$SUBNET" -d "$GATEWAY" -p tcp --dport "$SENTRY_RELAY_PORT" -j ACCEPT 2>/dev/null || true
iptables -I INPUT -s "$SUBNET" -d "$GATEWAY" -p tcp --dport "$SENTRY_RELAY_PORT" -j ACCEPT
