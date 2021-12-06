FROM python:3.10-slim

LABEL org.opencontainers.image.authors="livid@v2ex.com"

RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -yq --no-install-recommends libimage-exiftool-perl jhead libmagic-dev libpng-dev libjpeg-dev libwebp-dev libtiff-dev zlib1g-dev libfreetype-dev libheif-dev libde265-dev

COPY ./requirements.txt /app/requirements.txt
COPY ./dev/ipip.datx /opt/data/ipip.datx

WORKDIR /app

RUN pip3 install -r requirements.txt

COPY . /app

CMD [ "/usr/local/bin/gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "app:app" ]
