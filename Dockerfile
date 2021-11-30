FROM ubuntu:20.04

LABEL org.opencontainers.image.authors="livid@v2ex.com"

RUN apt-get update -y && \
    apt-get install -y python3-pip python3-dev libimage-exiftool-perl jhead libmagic-dev libmemcached-dev

COPY ./requirements.txt /app/requirements.txt

WORKDIR /app

RUN pip3 install -r requirements.txt

COPY . /app

CMD [ "/usr/local/bin/gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "app:app" ]
