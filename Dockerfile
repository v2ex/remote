FROM python:3.14-alpine

LABEL org.opencontainers.image.authors="livid@v2ex.com"

# - cairo: rasterizing SVG (cairocffi)
# - libmagic: MIME sniffing (python-magic)
# - ttf-dejavu: a font for the text in SVG
RUN apk add --no-cache cairo libmagic ttf-dejavu

COPY ./requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY . /app

WORKDIR /app

# This worker exists to keep risky parsing of untrusted files away from the main
# site, so it has no business being root either. See `make run` for the rest of
# the sandbox.
USER 10001:10001

EXPOSE 5000

# TODO read from config file instead of hardcode
CMD [ "gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "--worker-tmp-dir", "/dev/shm", "remote.app:app" ]
