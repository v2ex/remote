APP_NAME = "remote"

IMAGE_NAME = "${APP_NAME}"

build-image:
	docker build -t ${IMAGE_NAME}:latest .
