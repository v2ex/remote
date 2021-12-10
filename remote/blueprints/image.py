import base64
import io
import time
from dataclasses import dataclass
from enum import Enum, IntEnum, unique
from typing import Tuple

import cairosvg
import magic
import pillow_avif  # noqa: F401
from flask import Blueprint, current_app, request
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from resizeimage import resizeimage
from sentry_sdk import capture_exception, capture_message

from remote.wrapper import APIDoc, APIError, Methods, api_doc, error, success

# Please keep the blueprint definition at the top uniformly.
image_bp = Blueprint("image", __name__)

register_heif_opener()


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
    IMAGE_ICO = "image/vnd.microsoft.icon"

    @classmethod
    def all(cls):
        return [i.value for i in cls]


@dataclass
class ImageInfo:
    status: str = "ok"
    success: bool = True
    width: int = 0
    height: int = 0
    mime_type: str = ""
    binary_size: int = 0


@image_bp.route("/images/info", methods=Methods.common())
@api_doc(APIDoc(usage="Upload an image file and show its info like size and type"))
def images_info():
    if not (_uploaded := request.files.get("file")):
        return error(APIError(message="No file was uploaded"))
    uploaded = _uploaded.read()
    if not (mime := _get_mime(uploaded)):
        return error(APIError(message="Unable to determine the file type"))
    if not mime.startswith("image/"):
        return error(APIError(message="Non-image file was provided"))
    try:
        if mime == SupportedImageTypes.IMAGE_SVG.value:
            uploaded = cairosvg.svg2png(
                bytestring=uploaded,
                dpi=300,
                scale=1,
            )
        img: Image = Image.open(io.BytesIO(uploaded))
        width, height = img.size
        binary_size = len(uploaded)
    except Exception as e:  # noqa
        if current_app.config["SENTRY_ENVIRONMENT"] != "production":
            capture_exception(e)
            return error(
                APIError(message=f"Unable to determine the size of the image: {e}")
            )
        return error(APIError(message="Unable to determine the size of the image"))

    return success(
        ImageInfo(width=width, height=height, mime_type=mime, binary_size=binary_size)
    )


@image_bp.route("/images/prepare_jpeg", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload an image file in JPEG format "
        "and have its GPS info stripped, and auto rotated"
    )
)
def prepare_jpeg():
    # Check uploaded file is valid or not.
    if not (_uploaded := request.files.get("file")):
        return error(APIError(message="No file was uploaded"))
    uploaded = _uploaded.read()
    if not (mime := _get_mime(uploaded)):
        return error(APIError(message="Unable to determine the file type"))

    if not mime.startswith(SupportedImageTypes.IMAGE_JPEG.value):
        err = APIError(message="This endpoint is only for processing JPEG images")
        return error(err)

    # Now we have a valid JPEG.
    # Two things to do:
    #
    # 1. Remove GPS
    # 2. Auto Rotate
    try:
        uploaded_image = _load_from_bytes(uploaded)
        no_gps_img = _remove_gps(uploaded_image)
        rotated_img = _auto_rotated(no_gps_img)
        output_b64_content = _get_b64_content(rotated_img)
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message=f"Failed to prepare image: {e}"), status=500)
    return success(
        {
            "uploaded": {
                "size": len(uploaded),
                "mime": mime,
            },
            "status": "ok",
            "output": output_b64_content,
            "success": True,
        }
    )


@image_bp.route("/images/fit/<int:box>", methods=Methods.common())
@api_doc(
    APIDoc(usage="Upload an image file and fit it into a box of the specified size")
)
def fit(box: int):
    # Check uploaded file is valid or not.
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


@image_bp.route("/images/resize_avatar", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload an image file in supported format, and resize for website "
        f"avatars in the following sizes: {AvatarSize.supported_desc()}. "
        f"Supported formats are: {', '.join(SupportedImageTypes.all())}"
    )
)
def resize_avatar():
    # Check uploaded file is valid or not.
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

    # We can enlarge .ico with Nearest Neighbor
    if mime == SupportedImageTypes.IMAGE_ICO.value:
        img = img.resize((512, 512), Image.NEAREST)
        im_size = img.size
        uploaded = io.BytesIO()
        img.save(uploaded, format="PNG")
        uploaded = uploaded.getvalue()

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

            uploaded = io.BytesIO()
            img.save(uploaded, format="PNG")
            uploaded = uploaded.getvalue()

            im_size = img.size
        except Exception as e:  # noqa
            capture_exception(e)
            return error(APIError(message=f"Failed to convert SVG to PNG: {e}"))

    # Now we have a valid image, and we know its size and type.
    # Resize it to each size contained in `AvatarSize`.

    def _try_rescale(img: Image, target_size: int) -> bytes | None:
        if not all(i >= target_size for i in img.size):
            return
        return _rescale_avatar(img, target_size)

    start = time.time()
    try:
        image = _load_from_bytes(uploaded)
        rotated_image = _auto_rotated(image)

        # Confirmation basic avatar to resize.
        # Try to use max size avatar otherwise use original(rotated).
        base_avatar = rotated_image
        if _standard_avatar := _try_rescale(rotated_image, max(AvatarSize)):
            base_avatar = _load_from_bytes(_standard_avatar)

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


def _load_from_bytes(uploaded_data: bytes) -> Image:
    """Convert uploaded content to Image to handle."""
    with io.BytesIO() as buffered:
        buffered.write(uploaded_data)
        return Image.open(buffered).copy()


def _get_b64_content(image: Image) -> str:
    with io.BytesIO() as buffered:
        image.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")


def _get_mime(buffer: bytes) -> str | None:
    """Try to get the mime type of the uploaded data."""
    try:
        return magic.from_buffer(buffer, mime=True)
    except:  # noqa
        return None


def _remove_gps(image: Image) -> Image:
    """Remove GPS data from the image EXIF and return a new image."""
    copied_image = image.copy()
    exif = copied_image.getexif()
    # see more about magic number `0x8825` from
    # [Pillow](https://pillow.readthedocs.io/en/stable/releasenotes/8.2.0.html#image-getexif-exif-and-gps-ifd)
    exif.pop(0x8825, None)
    return copied_image


def _auto_rotated(image: Image) -> Image:
    """Auto-rotate the image according to its EXIF data and return a new image."""
    return ImageOps.exif_transpose(image)


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