FROM python:3.10-slim

LABEL org.opencontainers.image.authors="livid@v2ex.com"

RUN DEBIAN_FRONTEND=noninteractive \
    apt-get update \
    && apt-get install -yq --no-install-recommends \
    gcc libmagic-dev libpng-dev libjpeg-dev libwebp-dev libtiff-dev \
    zlib1g-dev libfreetype-dev libheif-dev libde265-dev libcairo2-dev libavif-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /app/requirements.txt
RUN pip3 install --upgrade pip \
 && pip3 install wheel \
 && pip3 install -r /app/requirements.txt \
 && rm -rf ~/.cache/pip

EXPOSE 5000

COPY . /app

WORKDIR /app

# TODO read from config file instead of hardcode
CMD [ "/usr/local/bin/gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "remote.app:app" ]
