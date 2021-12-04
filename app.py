#!/usr/bin/env python
# coding=utf-8

import base64
import io
import json
import os
import socket
import subprocess
import tempfile
import time
from typing import Tuple

import dns.resolver
import magic
import pyipip
import sentry_sdk
from flask import Flask, Response, request
from PIL import Image
from resizeimage import resizeimage
from sentry_sdk import capture_exception
from sentry_sdk.integrations.flask import FlaskIntegration

import config
from constants import JSON_MIME_TYPE

sentry_sdk.init(
    dsn=config.sentry_dsn,
    integrations=[FlaskIntegration()],
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    traces_sample_rate=1.0,
    # By default the SDK will try to use the SENTRY_RELEASE
    # environment variable, or infer a git commit
    # SHA as release, however you may want to set
    # something more human-readable.
    # release="myapp@1.0.0",
)

app = Flask(__name__)

started = time.time()

ipdb = pyipip.IPIPDatabase(config.ipip_db_path)


@app.route("/")
def home():
    o = {}
    return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)


@app.route("/ping")
def ping():
    o = {}
    o["status"] = "ok"
    o["message"] = "pong"
    o["uptime"] = time.time() - started
    return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)


@app.route("/hello")
def hello():
    o = {}
    o["status"] = "ok"
    o["uid"] = config.uid
    o["uptime"] = time.time() - started
    o["region"] = config.region
    o["country"] = config.country
    return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)


@app.route("/ipip/<ip>")
def ipip(ip):
    if ":" in ip:
        return Response(
            json.dumps({"status": "error", "message": "IPv6 is not supported"}),
            status=400,
            mimetype=JSON_MIME_TYPE,
        )
    try:
        socket.inet_aton(ip)
    except socket.error:
        return Response(
            json.dumps({"status": "error", "message": "Invalid IPv4 address provided"}),
            status=400,
            mimetype=JSON_MIME_TYPE,
        )
    record = ipdb.lookup(ip)
    if record is not None:
        data_list = record.split("\t")
    result = {}
    try:
        result["status"] = "ok"
        result["country"] = data_list[0]
        result["province"] = data_list[1]
        result["city"] = data_list[2]
        result["org"] = data_list[3]
        result["isp"] = data_list[4]
        result["latitude"] = data_list[5]
        result["longitude"] = data_list[6]
        result["timezone"] = data_list[7]
        result["tz_diff"] = data_list[8]
        result["cn_division_code"] = data_list[9]
        result["calling_code"] = data_list[10]
        result["country_code"] = data_list[11]
        result["continent_code"] = data_list[12]
        return Response(json.dumps(result), status=200, mimetype=JSON_MIME_TYPE)
    except Exception as e:  # noqa
        capture_exception(e)
        return Response(
            json.dumps({"status": "error", "message": "IP info not found"}),
            status=404,
            mimetype=JSON_MIME_TYPE,
        )


@app.route("/ip")
def ip():
    def extract_ip4(ip: str) -> str:
        return ip.replace("::ffff:", "")

    o = {}
    if "X-Forwarded-For" in request.headers:
        ip = request.headers["X-Forwarded-For"]
    else:
        ip = request.remote_addr
    o["ip"] = ip
    if "." in o["ip"]:
        # IPv4 address detected
        o["ip"] = extract_ip4(o["ip"])
        o["ipv4"] = o["ip"]
        o["ipv6"] = None
        o["ipv4_available"] = True
        o["ipv6_available"] = False
    else:
        # IPv6 address detected
        o["ipv4"] = None
        o["ipv6"] = o["ip"]
        o["ipv4_available"] = False
        o["ipv6_available"] = True
    return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)


@app.route("/dns/resolve")
def resolve():
    o = {}
    d = request.args.get("domain")
    if d is None:
        o["status"] = "error"
        o["message"] = 'Required parameter "domain" is missing'
    else:
        try:
            local_resolver = dns.resolver.Resolver()
            local_resolver.nameservers = config.nameservers
            rrsets = local_resolver.query(d)
            o["nameservers"] = config.nameservers
            now = time.time()
            ttl = rrsets.expiration - now
            o["ttl"] = ttl
            answers = []
            for rrset in rrsets:
                answers.append(rrset.to_text())
            if len(answers) > 0:
                o["status"] = "ok"
            else:
                o["status"] = "error"
            o["answers"] = answers
        except Exception as e:  # noqa
            o["status"] = "error"
            o["message"] = "Unable to resolve the specified domain: " + str(e)
    return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)


@app.route("/images/prepare_jpeg", methods=["GET", "POST"])
def prepare_jpeg():
    o = {}
    if request.method == "GET":
        o["status"] = "ok"
        o[
            "usage"
        ] = "Upload an image file in JPEG format and have its GPS info stripped, and auto rotated"  # noqa
    if request.method == "POST":
        o["uploaded"] = {}
        image = request.files["file"].read()
        o["uploaded"]["size"] = len(image)
        try:
            mime = magic.from_buffer(image, mime=True)
            o["uploaded"]["mime"] = mime
        except:  # noqa
            o["status"] = "error"
            o["message"] = "Unable to determine the MIME type of the uploaded file"
            return Response(
                json.dumps(o), status=400, mimetype="application/json;charset=utf-8"
            )
        if not mime.startswith("image/jpeg"):
            o["status"] = "error"
            o["message"] = "This endpoint is only for processing JPEG images"
        else:
            """
            Now we have a valid JPEG.
            Two things to do:

            - Remove GPS
            - Auto Rotate
            """
            fd, path = tempfile.mkstemp()
            try:
                with os.fdopen(fd, "wb") as tmp:
                    tmp.write(image)
                exiftool_path = _get_exiftool_path()
                if exiftool_path is None:
                    o["status"] = "error"
                    o["message"] = "exiftool not installed"
                    return Response(json.dumps(o), status=500, mimetype=JSON_MIME_TYPE)
                subprocess.call(
                    [
                        exiftool_path,
                        "-overwrite_original_in_place",
                        "-P",
                        "-gps:all=",
                        "-xmp:geotag=",
                        path,
                    ],
                    shell=False,
                )
                jhead_path = _get_jhead_path()
                if jhead_path is None:
                    o["status"] = "error"
                    o["message"] = "jhead not installed"
                    return Response(json.dumps(o), status=500, mimetype=JSON_MIME_TYPE)
                subprocess.call(
                    [jhead_path, "-v", "-exonly", "-autorot", path], shell=False
                )
                with open(path, "rb") as tmp:
                    _o = tmp.read()
                    o["output"] = base64.b64encode(_o).decode("utf-8")
                    o["status"] = "ok"
            finally:
                os.remove(path)
    return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)


@app.route("/images/fit/<int:box>", methods=["GET", "POST"])
def fit(box: int):
    start = time.time()
    o = {}
    if request.method == "GET":
        o["status"] = "ok"
        o[
            "usage"
        ] = u"Upload an image file and fit it into a box of the specified size"  # noqa
        return Response(
            json.dumps(o), status=200, mimetype="application/json;charset=utf-8"
        )
    if request.method == "POST":
        o["uploaded"] = {}
        uploaded = request.files["file"].read()
        o["uploaded"]["size"] = len(uploaded)
        mime = magic.from_buffer(uploaded, mime=True)
        o["uploaded"]["mime"] = mime
        if mime not in ["image/jpeg", "image/png", "image/gif"]:
            o["status"] = "error"
            o["message"] = "The uploaded file is not in a supported format"
            return Response(json.dumps(o), status=200, mimetype=JSON_MIME_TYPE)
        else:
            """
            Now we have a valid image.
            Fit it into a box of the specified size.
            """
            try:
                b, f = _rescale_aspect_ratio(uploaded, box)
                if b is None:
                    o["status"] = "error"
                    o["message"] = "Error occurred during rescaling"
                    return Response(
                        json.dumps(o),
                        status=500,
                        mimetype=JSON_MIME_TYPE,
                    )
                if "simple" in request.args:
                    return Response(b, status=200, mimetype="image/" + f.lower())
                o["output"] = base64.b64encode(b).decode("utf-8")
                o["status"] = "ok"
                end = time.time()
                o["start"] = start
                o["end"] = end
                elapsed = end - start
                o["cost"] = int(elapsed * 1000)
                return Response(json.dumps(o), status=200, mimetype=JSON_MIME_TYPE)
            except IOError as e:
                capture_exception(e)
                o["output"] = None
                o["status"] = "error"
                o["message"] = "Unable to fit the image: " + str(e)
                return Response(json.dumps(o), status=400, mimetype=JSON_MIME_TYPE)


@app.route("/images/resize_avatar", methods=["GET", "POST"])
def resize_avatar():
    o = {}
    if request.method == "GET":
        o["status"] = "ok"
        o[
            "usage"
        ] = "Upload an image file in PNG/JPG/GIF format, and resize for website avatars in three sizes: 24x24 / 48x48 / 73x73"  # noqa
    if request.method == "POST":
        o = {}
        if "file" in request.files:
            o["uploaded"] = {}
            uploaded = request.files["file"].read()
            o["uploaded"]["size"] = len(uploaded)
            try:
                mime = magic.from_buffer(uploaded, mime=True)
                o["uploaded"]["mime"] = mime
            except:  # noqa
                o["status"] = "error"
                o["message"] = "Unable to determine the file type"
                return Response(json.dumps(o), status=400, mimetype=JSON_MIME_TYPE)
            try:
                im = Image.open(io.BytesIO(uploaded))
                im_size = im.size
            except:  # noqa
                o["status"] = "error"
                o["message"] = "Unable to determine the size of the image"
                return Response(json.dumps(o), status=400, mimetype=JSON_MIME_TYPE)
            if mime not in [
                "image/jpeg",
                "image/png",
                "image/gif",
                "image/webp",
                "image/bmp",
                "image/tiff",
            ]:
                o["status"] = "error"
                o["message"] = "The uploaded file is not in a supported format"
                return Response(json.dumps(o), status=400, mimetype=JSON_MIME_TYPE)
            else:
                """
                Now we have a valid image and we know its size and type.
                Resize it to 6 different sizes:

                - 24x24 (mini)
                - 48x48 (normal)
                - 73x73 (large)
                - 128x128 (xl)
                - 256x256 (xxl)
                - 512x512 (xxxl)
                """
                try:
                    start = time.time()

                    avatar24 = _rescale_avatar(uploaded, 24)
                    o["avatar24"] = {}
                    o["avatar24"]["size"] = len(avatar24)
                    o["avatar24"]["body"] = base64.b64encode(avatar24).decode("utf-8")

                    avatar48 = _rescale_avatar(uploaded, 48)
                    o["avatar48"] = {}
                    o["avatar48"]["size"] = len(avatar48)
                    o["avatar48"]["body"] = base64.b64encode(avatar48).decode("utf-8")

                    avatar73 = _rescale_avatar(uploaded, 73)
                    o["avatar73"] = {}
                    o["avatar73"]["size"] = len(avatar73)
                    o["avatar73"]["body"] = base64.b64encode(avatar73).decode("utf-8")

                    if im_size[0] >= 128 and im_size[1] >= 128:
                        avatar128 = _rescale_avatar(uploaded, 128)
                        o["avatar128"] = {}
                        o["avatar128"]["size"] = len(avatar128)
                        o["avatar128"]["body"] = base64.b64encode(avatar128).decode(
                            "utf-8"
                        )

                    if im_size[0] >= 256 and im_size[1] >= 256:
                        avatar256 = _rescale_avatar(uploaded, 256)
                        o["avatar256"] = {}
                        o["avatar256"]["size"] = len(avatar256)
                        o["avatar256"]["body"] = base64.b64encode(avatar256).decode(
                            "utf-8"
                        )

                    if im_size[0] >= 512 and im_size[1] >= 512:
                        avatar512 = _rescale_avatar(uploaded, 512)
                        o["avatar512"] = {}
                        o["avatar512"]["size"] = len(avatar512)
                        o["avatar512"]["body"] = base64.b64encode(avatar512).decode(
                            "utf-8"
                        )

                    end = time.time()
                    elapsed = end - start
                    o["cost"] = int(elapsed * 1000)
                    o["status"] = "ok"
                    return Response(
                        json.dumps(o),
                        status=200,
                        mimetype=JSON_MIME_TYPE,
                    )
                except Exception as e:  # noqa
                    capture_exception(e)
                    o["status"] = "error"
                    o["message"] = "Failed to resize the uploaded image file: " + str(e)
                    return Response(
                        json.dumps(o),
                        status=400,
                        mimetype=JSON_MIME_TYPE,
                    )
        else:
            o["status"] = "error"
            o["message"] = "No file was uploaded"
            return Response(json.dumps(o), status=400, mimetype=JSON_MIME_TYPE)


def _rescale_avatar(data: bytes, box: int) -> bytes | None:
    try:
        f = io.BytesIO(data)
        with Image.open(f) as image:
            thumbnail = resizeimage.resize_cover(image, [box, box], validate=False)
            o = io.BytesIO()
            thumbnail.save(o, format="PNG")
            v = o.getvalue()
            o.close()
            f.close()
            return v
    except Exception as e:  # noqa
        capture_exception(e)
        return None


def _rescale_aspect_ratio(data: bytes, box: int) -> Tuple[bytes | None, str | None]:
    try:
        f = io.BytesIO(data)
        with Image.open(f) as image:
            thumbnail = resizeimage.resize_thumbnail(image, [box, box])
            o = io.BytesIO()
            thumbnail.save(o, format=image.format)
            v = o.getvalue()
            o.close()
            f.close()
            return v, image.format
    except Exception as e:  # noqa
        capture_exception(e)
        return None, None


def _get_exiftool_path() -> str | None:
    locations = ["/usr/bin/exiftool", "/opt/homebrew/bin/exiftool"]
    for location in locations:
        if os.path.exists(location):
            return location
    return None


def _get_jhead_path() -> str | None:
    locations = ["/usr/bin/jhead", "/opt/homebrew/bin/jhead"]
    for location in locations:
        if os.path.exists(location):
            return location
    return None
