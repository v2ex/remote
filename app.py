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
from collections import namedtuple
from dataclasses import asdict, dataclass
from enum import Enum, unique
from typing import List, Tuple

import dns.resolver
import magic
import pillow_avif  # noqa
import pyipip
import sentry_sdk
from dns.exception import DNSException
from flask import Flask, Response, request
from PIL import ExifTags, Image
from pillow_heif import register_heif_opener
from resizeimage import resizeimage
from sentry_sdk import capture_exception, capture_message
from sentry_sdk.integrations.flask import FlaskIntegration

import config
from constants import JSON_MIME_TYPE

register_heif_opener()

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


@dataclass
class APIDoc:
    usage: str
    status: str = "ok"


@dataclass
class APIError:
    message: str
    status: str = "error"


@app.route("/")
def home():
    return Response(json.dumps({}), mimetype=JSON_MIME_TYPE)


@dataclass
class Pong:
    status: str = "ok"
    message: str = "pong"
    uptime: float = time.time() - started


@app.route("/ping")
def ping():
    pong = asdict(Pong())
    return Response(json.dumps(pong), mimetype=JSON_MIME_TYPE)


@dataclass
class AccessMeta:
    status: str = "ok"
    uid: str = config.uid
    uptime: float = time.time() - started
    country: str = config.country
    region: str = config.region


@app.route("/hello")
def hello():
    access_meta = asdict(AccessMeta())
    return Response(json.dumps(access_meta), mimetype=JSON_MIME_TYPE)


IPRecord = namedtuple(
    "IPRecord",
    [
        "status",
        "country",
        "province",
        "city",
        "org",
        "isp",
        "latitude",
        "longitude",
        "timezone",
        "tz_diff",
        "cn_division_code",
        "calling_code",
        "country_code",
        "continent_code",
    ],
)


@app.route("/ipip/<ip>")
def ipip(ip):
    if ":" in ip:
        api_error = APIError(message="IPv6 is not supported")
        return Response(
            json.dumps(asdict(api_error)), status=400, mimetype=JSON_MIME_TYPE
        )

    try:
        socket.inet_aton(ip)
    except socket.error:
        api_error = APIError(message="Invalid IPv4 address provided")
        return Response(
            json.dumps(asdict(api_error)), status=400, mimetype=JSON_MIME_TYPE
        )

    try:
        record = ipdb.lookup(ip)
        data_list = [] if record is None else record.split()
        # remove a `status` field that we assigned.
        except_ip_meta_length = len(IPRecord._fields) - 1
        ip_record = IPRecord("ok", *data_list[:except_ip_meta_length])
    except Exception as e:  # noqa
        capture_exception(e)
        api_error = APIError(message="IP info not found")
        return Response(
            json.dumps(asdict(api_error)), status=404, mimetype=JSON_MIME_TYPE
        )

    return Response(json.dumps(ip_record._asdict()), mimetype=JSON_MIME_TYPE)


@dataclass
class UserIP:
    ip: str
    ipv4: str = None
    ipv6: str = None
    ipv4_available: bool = None
    ipv6_available: bool = None

    def __post_init__(self):
        self.ipv4 = self.extract_ip4(self.ip) if self.is_ipv4 else None
        self.ipv6 = None if self.is_ipv4 else self.ip
        self.ipv4_available = self.is_ipv4
        self.ipv6_available = not self.is_ipv4

    @property
    def is_ipv4(self) -> bool:
        return "." in self.ip

    @staticmethod
    def extract_ip4(raw_ip: str) -> str:
        return raw_ip.replace("::ffff:", "")  # noqa


@app.route("/ip")
def ip():
    _ip = request.remote_addr
    if "X-Forwarded-For" in request.headers:
        _ip = request.headers["X-Forwarded-For"]
    user_ip = UserIP(ip=_ip)
    return Response(json.dumps(asdict(user_ip)), mimetype=JSON_MIME_TYPE)


@dataclass
class ResolveResp:
    ttl: float
    answers: List
    nameservers: List[str]
    status: str = None  # TODO should be bool?

    def __post_init__(self):
        self.status = "ok" if len(self.answers) > 0 else "error"


@app.route("/dns/resolve")
def resolve():
    if not (domain := request.args.get("domain")):
        resp = APIError(message='Required parameter "domain" is missing or empty')
        return Response(json.dumps(resp), status=400, mimetype=JSON_MIME_TYPE)

    local_resolver = dns.resolver.Resolver()
    local_resolver.nameservers = config.nameservers
    try:
        dns_answer = local_resolver.resolve(domain)
    except DNSException as e:
        resp = APIError(message=f"Unable to resolve the specified domain: {e}")
        return Response(json.dumps(resp), status=400, mimetype=JSON_MIME_TYPE)

    resolve_resp = ResolveResp(
        nameservers=config.nameservers,
        ttl=dns_answer.expiration - time.time(),
        answers=[rrset.to_text() for rrset in dns_answer],
    )
    return Response(json.dumps(asdict(resolve_resp)), mimetype=JSON_MIME_TYPE)


@unique
class SupportImgMIME(Enum):
    IMAGE_JPEG = "image/jpeg"
    IMAGE_PNG = "image/png"
    IMAGE_GIF = "image/gif"
    IMAGE_WEBP = "image/webp"
    IMAGE_BMP = "image/bmp"
    IMAGE_TIFF = "image/tiff"

    @classmethod
    def all(cls):
        return [i.value for i in cls]

    @classmethod
    def processing_support(cls):
        return [
            cls.IMAGE_JPEG.value,
            cls.IMAGE_PNG.value,
            cls.IMAGE_GIF.value,
        ]


@app.route("/images/prepare_jpeg", methods=["GET", "POST"])
def prepare_jpeg():
    if request.method == "GET":
        api_doc = APIDoc(
            usage="Upload an image file in JPEG format "
            "and have its GPS info stripped, and auto rotated"
        )
        return Response(json.dumps(api_doc), mimetype=JSON_MIME_TYPE)

    o = {}
    if request.method == "POST":
        o["uploaded"] = {}
        image = request.files["file"].read()
        o["uploaded"]["size"] = len(image)
        try:
            mime = magic.from_buffer(image, mime=True)
            o["uploaded"]["mime"] = mime
        except:  # noqa
            api_error = APIError(
                message="Unable to determine the MIME type of the uploaded file"
            )
            return Response(
                json.dumps(asdict(api_error)), status=400, mimetype=JSON_MIME_TYPE
            )
        if not mime.startswith(SupportImgMIME.IMAGE_JPEG.value):
            api_error = APIError(
                message="This endpoint is only for processing JPEG images"
            )
            return Response(
                json.dumps(asdict(api_error)), status=400, mimetype=JSON_MIME_TYPE
            )
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
                    api_error = APIError(message="exiftool not installed")
                    return Response(
                        json.dumps(asdict(api_error)),
                        status=500,
                        mimetype=JSON_MIME_TYPE,
                    )
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
                    api_error = APIError(message="jhead not installed")
                    return Response(
                        json.dumps(asdict(api_error)),
                        status=500,
                        mimetype=JSON_MIME_TYPE,
                    )
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
    if request.method == "GET":
        api_doc = APIDoc(
            usage="Upload an image file and fit it into a box of the specified size"
        )
        return Response(json.dumps(asdict(api_doc)), mimetype=JSON_MIME_TYPE)

    start = time.time()
    o = {}
    if request.method == "POST":
        o["uploaded"] = {}
        uploaded = request.files["file"].read()
        o["uploaded"]["size"] = len(uploaded)
        mime = magic.from_buffer(uploaded, mime=True)
        o["uploaded"]["mime"] = mime
        if mime not in SupportImgMIME.processing_support():
            api_error = APIError(
                message="The uploaded file is not in a supported format"
            )
            return Response(
                json.dumps(asdict(api_error)), status=400, mimetype=JSON_MIME_TYPE
            )
        else:
            """
            Now we have a valid image.
            Fit it into a box of the specified size.
            """
            try:
                b, f = _rescale_aspect_ratio(uploaded, box)
                if b is None:
                    api_error = APIError(message="Error occurred during rescaling")
                    return Response(
                        json.dumps(asdict(api_error)),
                        status=500,
                        mimetype=JSON_MIME_TYPE,
                    )
                if "simple" in request.args:
                    return Response(b, mimetype="image/" + f.lower())
                o["output"] = base64.b64encode(b).decode("utf-8")
                o["status"] = "ok"
                end = time.time()
                o["start"] = start
                o["end"] = end
                elapsed = end - start
                o["cost"] = int(elapsed * 1000)
                return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)
            except IOError as e:
                capture_exception(e)
                o["output"] = None
                o["status"] = "error"
                o["message"] = "Unable to fit the image: " + str(e)
                return Response(json.dumps(o), status=400, mimetype=JSON_MIME_TYPE)


@app.route("/images/resize_avatar", methods=["GET", "POST"])
def resize_avatar():
    if request.method == "GET":
        api_doc = APIDoc(
            usage="Upload an image file in PNG/JPG/GIF format, "
            "and resize for website avatars in three sizes: 24x24 / 48x48 / 73x73"
        )
        return Response(json.dumps(api_doc), mimetype=JSON_MIME_TYPE)
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
                api_error = APIError(message="Unable to determine the file type")
                return Response(
                    json.dumps(asdict(api_error)), status=400, mimetype=JSON_MIME_TYPE
                )
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
                "image/heif",
                "image/heic",
                "image/jp2",
                "image/vnd.adobe.photoshop",
                "image/x-icns",
            ]:
                if mime.startswith("image/"):
                    capture_message("Unsupported image type received: " + mime)
                o["status"] = "error"
                o["message"] = "The uploaded file is not in a supported format"
                return Response(json.dumps(o), status=400, mimetype=JSON_MIME_TYPE)
            else:
                """
                We need to rotate the JPEG image if it has Orientation tag.
                """
                if mime == "image/jpeg":
                    for orientation in ExifTags.TAGS.keys():
                        if ExifTags.TAGS[orientation] == "Orientation":
                            break

                    exif = im._getexif()

                    if exif is not None and orientation in exif:
                        if exif[orientation] == 3:
                            im = im.rotate(180, expand=True)
                        elif exif[orientation] == 6:
                            im = im.rotate(270, expand=True)
                        elif exif[orientation] == 8:
                            im = im.rotate(90, expand=True)

                    im_size = im.size

                    rotated = io.BytesIO()
                    im.save(rotated, format="JPEG", quality=95)
                    uploaded = rotated.getvalue()

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

                    avatar512 = None
                    if im_size[0] >= 512 and im_size[1] >= 512:
                        avatar512 = _rescale_avatar(uploaded, 512)
                        o["avatar512"] = {}
                        o["avatar512"]["size"] = len(avatar512)
                        o["avatar512"]["body"] = base64.b64encode(avatar512).decode(
                            "utf-8"
                        )
                    if avatar512 is not None:
                        upstream = avatar512
                    else:
                        upstream = uploaded

                    sizes = [256, 128, 73, 48, 24]
                    for size in sizes:
                        if im_size[0] >= size and im_size[1] >= size:
                            avatar = _rescale_avatar(upstream, size)
                            o["avatar" + str(size)] = {}
                            o["avatar" + str(size)]["size"] = len(avatar)
                            o["avatar" + str(size)]["body"] = base64.b64encode(
                                avatar
                            ).decode("utf-8")

                    end = time.time()
                    elapsed = end - start
                    o["cost"] = int(elapsed * 1000)
                    o["status"] = "ok"
                    return Response(json.dumps(o), mimetype=JSON_MIME_TYPE)
                except Exception as e:  # noqa
                    capture_exception(e)
                    api_error = APIError(
                        message=f"Failed to resize the uploaded image file: {e}"
                    )
                    return Response(
                        json.dumps(asdict(api_error)),
                        status=400,
                        mimetype=JSON_MIME_TYPE,
                    )
        else:
            api_error = APIError(message="No file was uploaded")
            return Response(
                json.dumps(asdict(api_error)), status=400, mimetype=JSON_MIME_TYPE
            )


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
    return next((location for location in locations if os.path.exists(location)), None)


def _get_jhead_path() -> str | None:
    locations = ["/usr/bin/jhead", "/opt/homebrew/bin/jhead"]
    return next((location for location in locations if os.path.exists(location)), None)
