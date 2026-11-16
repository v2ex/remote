# Config for the container, one `KEY=value` per line.
# The keys are the ones defined in `remote/config/base.py`.
ENV_FILE ?= remote.env
# Directory holding the files the config points to, e.g. `ipip.datx`.
DATA_DIR ?= /opt/data

# The image installs exactly what `requirements.lock` lists, checked by hash.
# This re-resolves `requirements.txt` to the newest versions, in the image's own
# Python so the lock matches what the image can install. Test the image built from
# a new lock before shipping it.
lock:
	docker run --rm -e CUSTOM_COMPILE_COMMAND="make lock" \
		-v $(CURDIR)/requirements.txt:/src/requirements.txt:ro -w /src \
		$(shell awk '/^FROM/ {print $$2; exit}' Dockerfile) sh -c \
		'pip install -q --root-user-action=ignore --disable-pip-version-check pip-tools >&2 \
		&& pip-compile -q --generate-hashes --strip-extras -o - requirements.txt' \
		> requirements.lock.new
	mv requirements.lock.new requirements.lock

build-image:
	docker build -t remote:latest .

# The worker never opens a connection of its own, so ffmpeg can't either: the
# container sits on its own bridge, and the host drops anything that subnet
# starts, to the internet, the tailnet or the host itself. Answers to requests
# on the published port still go out. The one way out is Sentry: nginx on the
# host relays the worker's events to it from the bridge's gateway (on licht,
# /etc/nginx/sites-available/remote-sentry-relay), so SENTRY_DSN is
# http://<key>@$(GATEWAY):$(SENTRY_RELAY_PORT)/<project>, and only that port is
# let through, ahead of the drop. Needs root; iptables rules don't survive a
# reboot, so run it again after one (`run` does too).
NETWORK ?= remote-sandbox
SUBNET ?= 172.31.250.0/24
GATEWAY ?= 172.31.250.1
SENTRY_RELAY_PORT ?= 9009
sandbox:
	docker network inspect $(NETWORK) >/dev/null 2>&1 \
		|| docker network create --subnet $(SUBNET) --gateway $(GATEWAY) $(NETWORK)
	for chain in DOCKER-USER INPUT; do \
		iptables -C $$chain -s $(SUBNET) -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP 2>/dev/null \
		|| iptables -I $$chain -s $(SUBNET) -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP; \
	done
	# Re-inserted each time, so it always sits above the drop.
	iptables -D INPUT -s $(SUBNET) -d $(GATEWAY) -p tcp --dport $(SENTRY_RELAY_PORT) -j ACCEPT 2>/dev/null || true
	iptables -I INPUT -s $(SUBNET) -d $(GATEWAY) -p tcp --dport $(SENTRY_RELAY_PORT) -j ACCEPT

# The worker parses untrusted files, so the container gets as little as possible:
# no root, no capabilities, no network of its own (see `sandbox`), read-only
# filesystem, bounded memory and processes. /tmp holds a video and its stripped
# copy per request (95MB each), and its pages count against the memory limit.
run: sandbox
	docker run --name=remote --restart=always -p 127.0.0.1:5000:5000 -d \
		--network $(NETWORK) \
		--env-file $(ENV_FILE) -v $(DATA_DIR):/opt/data:ro \
		--read-only --tmpfs /tmp:rw,noexec,nosuid,size=2g \
		--cap-drop=ALL --security-opt=no-new-privileges \
		--memory=4g --memory-swap=4g --pids-limit=256 \
		remote:latest

dev:
	FLASK_DEBUG=true flask run --host=:: --port=5000
