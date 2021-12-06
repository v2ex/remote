FROM python:3.10

LABEL org.opencontainers.image.authors="livid@v2ex.com"

RUN apt-get update -y && \
    apt-get install -y python3-pip python3-dev libimage-exiftool-perl jhead libmagic-dev libpng-dev libjpeg-dev libwebp-dev libtiff-dev zlib1g-dev libfreetype-dev libheif-dev

COPY ./requirements.txt /app/requirements.txt
COPY ./dev/ipip.datx /opt/data/ipip.datx

WORKDIR /app

RUN pip3 install -r requirements.txt

COPY . /app

CMD [ "/usr/local/bin/gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "app:app" ]
