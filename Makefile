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

# The worker parses untrusted files, so the container gets as little as possible:
# no root, no capabilities, read-only filesystem, bounded memory and processes.
run:
	docker run --name=remote --restart=always -p 127.0.0.1:5000:5000 -d \
		--env-file $(ENV_FILE) -v $(DATA_DIR):/opt/data:ro \
		--read-only --tmpfs /tmp \
		--cap-drop=ALL --security-opt=no-new-privileges \
		--memory=4g --memory-swap=4g --pids-limit=256 \
		remote:latest

dev:
	FLASK_DEBUG=true flask run --host=:: --port=5000
