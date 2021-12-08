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
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum, IntEnum, unique
from functools import partial, wraps
from typing import Any, List, Tuple

import cairosvg
import dns.resolver
import magic
import pillow_avif  # noqa
import pyipip
import sentry_sdk
from dns.exception import DNSException
from flask import Flask, Response, request
from PIL import Image, ImageOps
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
    # By default, the SDK will try to use the SENTRY_RELEASE
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
    success: bool = True


def api_doc(doc: APIDoc):
    """To decorate the `get` method to return the description of the API."""

    def wrapper(func):
        @wraps(func)
        def inner(*args, **kwargs):
            if request.method == "GET":
                return success(doc)

            return func(*args, **kwargs)

        return inner

    return wrapper


def _response(content: Any, status: int, mimetype: str = JSON_MIME_TYPE, **kwargs):
    if is_dataclass(content):
        content = json.dumps(asdict(content))
    elif isinstance(content, dict):
        content = json.dumps(content)
    return Response(response=content, status=status, mimetype=mimetype, **kwargs)


error = partial(_response, status=400)
success = partial(_response, status=200)


@dataclass
class APIError:
    message: str
    status: str = "error"
    success: bool = False


@app.route("/")
def home():
    return success({})


@dataclass
class Pong:
    status: str = "ok"
    message: str = "pong"
    uptime: float = field(default_factory=lambda: time.time() - started)
    success: bool = True


@app.route("/ping")
def ping():
    return success(Pong())


@dataclass
class WorkerInfo:
    status: str = "ok"
    uid: str = config.uid
    uptime: float = field(default_factory=lambda: time.time() - started)
    country: str = config.country
    region: str = config.region
    success: bool = True


@app.route("/hello")
def hello():
    return success(WorkerInfo())


IPRecord = namedtuple(
    "IPRecord",
    [
        "status",
        "success",
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
        return error(APIError(message="IPv6 is not supported"))

    try:
        socket.inet_aton(ip)
    except socket.error:
        return error(APIError(message="Invalid IPv4 address provided"))

    try:
        ip_fields = ipdb.lookup(ip).split("\t")
        # subtract the number of fields that we own assigned.
        except_ip_meta_length = len(IPRecord._fields) - 2
        ip_record = IPRecord("ok", True, *ip_fields[:except_ip_meta_length])
        return success(ip_record._asdict())
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message="IP info not found"), status=404)


@dataclass
class UserIP:
    ip: str
    ipv4: str = None
    ipv6: str = None
    ipv4_available: bool = None
    ipv6_available: bool = None
    success: bool = True

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
    if forwarded := request.headers.get("X-Forwarded-For"):
        _ip = forwarded
    return success(UserIP(ip=_ip))


@dataclass
class ResolveResp:
    ttl: float
    answers: List
    nameservers: List[str]
    status: str = None
    success: bool = True

    def __post_init__(self):
        self.status = "ok" if len(self.answers) > 0 else "error"


@app.route("/dns/resolve")
def resolve():
    if not (domain := request.args.get("domain")):
        api_error = APIError(message='Required parameter "domain" is missing or empty')
        return error(api_error)

    local_resolver = dns.resolver.Resolver()
    local_resolver.nameservers = config.nameservers
    try:
        dns_answer = local_resolver.resolve(domain)
    except DNSException as e:
        return error(APIError(message=f"Unable to resolve the specified domain: {e}"))

    resolve_resp = ResolveResp(
        nameservers=config.nameservers,
        ttl=dns_answer.expiration - time.time(),
        answers=[rrset.to_text() for rrset in dns_answer],
    )
    return success(resolve_resp)


@unique
class SupportedImageTypes(Enum):
    IMAGE_JPEG = "image/jpeg"
    IMAGE_PNG = "image/png"
    IMAGE_GIF = "image/gif"
    IMAGE_WEBP = "image/webp"
    IMAGE_BMP = "image/bmp"
    IMAGE_TIFF = "image/tiff"
    IMAGE_HEIF = "image/heif"
    IMAGE_HEIC = "image/heic"
    IMAGE_JP2 = "image/jp2"
    IMAGE_VND_ADOBE_PHOTOSHOP = "image/vnd.adobe.photoshop"
    IMAGE_X_ICNS = "image/x-icns"
    IMAGE_SVG = "image/svg+xml"

    @classmethod
    def all(cls):
        return [i.value for i in cls]


@api_doc(
    APIDoc(
        usage="Upload an image file in JPEG format "
        "and have its GPS info stripped, and auto rotated"
    )
)
@app.route("/images/prepare_jpeg", methods=["GET", "POST"])
def prepare_jpeg():
    # check uploaded file is valid or not
    if not (_uploaded := request.files.get("file")):
        return error(APIError(message="No file was uploaded"))
    uploaded = _uploaded.read()
    if not (mime := _get_mime(uploaded)):
        return error(APIError(message="Unable to determine the file type"))

    if not mime.startswith(SupportedImageTypes.IMAGE_JPEG.value):
        err = APIError(message="This endpoint is only for processing JPEG images")
        return error(err)

    # check extra tools on system
    # TODO replace extra tools(`exiftool`/`jhead`) with PIL.
    if not (exiftool_path := _get_exiftool_path()):
        return error(APIError(message="exiftool not installed"), status=500)
    if not (jhead_path := _get_jhead_path()):
        return error(APIError(message="jhead not installed"), status=500)

    # Now we have a valid JPEG.
    # Two things to do:
    #
    # 1. Remove GPS
    # 2. Auto Rotate
    fd, path = tempfile.mkstemp()
    try:
        # 1. Remove GPS by using `exiftool`.
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(uploaded)
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
        # 2. Auto rotate by using `jhead`.
        subprocess.call([jhead_path, "-v", "-exonly", "-autorot", path], shell=False)
        with open(path, "rb") as tmp:
            prepared = base64.b64encode(tmp.read()).decode("utf-8")
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message=f"Failed to prepare image: {e}"), status=500)
    finally:
        os.remove(path)

    return success(
        {
            "uploaded": {
                "size": len(uploaded),
                "mime": mime,
            },
            "status": "ok",
            "output": prepared,
            "success": True,
        }
    )


@api_doc(
    APIDoc(usage="Upload an image file and fit it into a box of the specified size")
)
@app.route("/images/fit/<int:box>", methods=["GET", "POST"])
def fit(box: int):
    # check uploaded file is valid or not
    if not (_uploaded := request.files.get("file")):
        return error(APIError(message="No file was uploaded"))
    uploaded = _uploaded.read()
    if not (mime := _get_mime(uploaded)):
        return error(APIError(message="Unable to determine the file type"))

    if mime not in SupportedImageTypes.all():
        return error(APIError(message="The uploaded file is not in a supported format"))

    # Now we have a valid image.
    # Fit it into a box of the specified size.
    start = time.time()
    _resized_content, format_name = _rescale_aspect_ratio(uploaded, box)
    if _resized_content is None:
        return error(APIError(message="Error occurred during rescaling"), status=500)

    resized_content = base64.b64encode(_resized_content).decode("utf-8")
    if request.args.get("simple"):
        return success(resized_content, mimetype=f"image/{format_name.lower()}")

    end = time.time()
    return success(
        {
            "uploaded": {
                "size": len(uploaded),
                "mime": mime,
            },
            "status": "ok",
            "success": True,
            "start": start,
            "end": end,
            "cost": int((end - start) * 1000),
            "output": resized_content,
        }
    )


@unique
class AvatarSize(IntEnum):
    MINI = 24
    NORMAL = 48
    LARGE = 73
    XL = 128
    XXL = 256
    XXXL = 512

    @classmethod
    def supported_desc(cls):
        return " / ".join(f"{i}x{i}" for i in cls)

    @property
    def is_mandatory(self):
        return self in [
            self.MINI.value,
            self.NORMAL.value,
            self.LARGE.value,
        ]


@api_doc(
    APIDoc(
        usage="Upload an image file in supported format, and resize for website "
        f"avatars in the following sizes: {AvatarSize.supported_desc()}. "
        f"Supported formats are: {', '.join(SupportedImageTypes.all())}"
    )
)
@app.route("/images/resize_avatar", methods=["GET", "POST"])
def resize_avatar():
    # check uploaded file is valid or not
    if not (_uploaded := request.files.get("file")):
        return error(APIError(message="No file was uploaded"))
    uploaded = _uploaded.read()
    if not (mime := _get_mime(uploaded)):
        return error(APIError(message="Unable to determine the file type"))

    if mime not in SupportedImageTypes.all():
        if mime.startswith("image/"):
            capture_message(f"Unsupported image type received: {mime}")
        return error(APIError(message="The uploaded file is not in a supported format"))

    try:
        if mime != SupportedImageTypes.IMAGE_SVG.value:
            img: Image = Image.open(io.BytesIO(uploaded))
            im_size = img.size
    except:  # noqa
        return error(APIError(message="Unable to determine the size of the image"))

    # We need to rotate the JPEG image if it has Orientation tag.
    if mime == SupportedImageTypes.IMAGE_JPEG.value:
        img = ImageOps.exif_transpose(img)
        im_size = img.size

    # We need to convert SVG to PNG
    if mime == SupportedImageTypes.IMAGE_SVG.value:
        try:
            uploaded = cairosvg.svg2png(
                bytestring=uploaded,
                dpi=300,
                scale=2,
            )
            img = Image.open(io.BytesIO(uploaded))
            im_size = img.size

            if im_size[0] > im_size[1]:
                background = Image.new("RGBA", (im_size[0], im_size[0]), (0, 0, 0, 0))
                x = 0
                y = int((im_size[0] - im_size[1]) / 2)
                background.paste(img, (x, y))
            else:
                background = Image.new("RGBA", (im_size[1], im_size[1]), (0, 0, 0, 0))
                x = int((im_size[1] - im_size[0]) / 2)
                y = 0
                background.paste(img, (x, y))

            img = background

            im_size = img.size
        except Exception as e:  # noqa
            capture_exception(e)
            return error(APIError(message=f"Failed to convert SVG to PNG: {e}"))

    # Now we have a valid image, and we know its size and type.
    # Resize it to each size contained in `AvatarSize`.

    def _try_rescale(image: Image, box_size: int) -> bytes | None:
        if not all(i >= box_size for i in im_size):
            return
        return _rescale_avatar(image, box_size)

    start = time.time()
    try:
        base_avatar_data = _try_rescale(img, max(AvatarSize)) or uploaded
        base_avatar = Image.open(io.BytesIO(base_avatar_data))
        avatars = {}
        for size in AvatarSize:
            rescaled_avatar_data = None
            if size.is_mandatory:
                rescaled_avatar_data = _rescale_avatar(base_avatar, size)
            elif avatar_data := _try_rescale(base_avatar, size):
                rescaled_avatar_data = avatar_data

            if rescaled_avatar_data:
                avatars[f"avatar{size}"] = {
                    "size": len(rescaled_avatar_data),
                    "body": base64.b64encode(rescaled_avatar_data).decode("utf-8"),
                }
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message=f"Failed to resize the uploaded image file: {e}"))
    end = time.time()
    return success(
        {
            "uploaded": {
                "size": len(uploaded),
                "mime": mime,
            },
            "status": "ok",
            "success": True,
            "start": start,
            "end": end,
            "cost": int((end - start) * 1000),
            **avatars,
        }
    )


def _get_mime(buffer: bytes) -> str | None:
    try:
        return magic.from_buffer(buffer, mime=True)
    except:  # noqa
        return None


def _rescale_avatar(image: Image, box: int) -> bytes | None:
    try:
        with io.BytesIO() as io_obj:
            thumbnail = resizeimage.resize_cover(image, [box, box], validate=False)
            thumbnail.save(io_obj, format="PNG")
            return io_obj.getvalue()
    except Exception as e:  # noqa
        capture_exception(e)
        return None


def _rescale_aspect_ratio(data: bytes, box: int) -> Tuple[bytes | None, str | None]:
    try:
        with Image.open(io.BytesIO(data)) as image, io.BytesIO() as io_obj:
            thumbnail = resizeimage.resize_thumbnail(image, [box, box])
            thumbnail.save(io_obj, format=image.format)
            return io_obj.getvalue(), image.format
    except Exception as e:  # noqa
        capture_exception(e)
        return None, None


def _get_exiftool_path() -> str | None:
    locations = ["/usr/bin/exiftool", "/opt/homebrew/bin/exiftool"]
    return next((location for location in locations if os.path.exists(location)), None)


def _get_jhead_path() -> str | None:
    locations = ["/usr/bin/jhead", "/opt/homebrew/bin/jhead"]
    return next((location for location in locations if os.path.exists(location)), None)
