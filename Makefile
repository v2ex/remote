build-image:
	docker build -t remote:latest .

run:
	docker run --name=remote --restart=always -p 127.0.0.1:5000:5000 -d remote:latest
