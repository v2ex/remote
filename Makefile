# Config for the container, one `KEY=value` per line.
# The keys are the ones defined in `remote/config/base.py`.
ENV_FILE ?= remote.env
# Directory holding the files the config points to, e.g. `ipip.datx`.
DATA_DIR ?= /opt/data

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
