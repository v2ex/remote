import base64
import io
import time
from dataclasses import dataclass

import pillow_avif  # noqa: F401
from flask import Blueprint, request
from PIL import Image
from resizeimage import resizeimage
from sentry_sdk import capture_exception

from remote.utilities.image import AvatarSize, ExifTag, ImageHandle, ImageMIME
from remote.wrapper import APIDoc, APIError, Methods, api_doc, error, success

# Please keep the blueprint definition at the top uniformly.
image_bp = Blueprint("image", __name__)


@dataclass
class ImageInfo:
    status: str = "ok"
    success: bool = True
    width: int = 0
    height: int = 0
    mime_type: str = ""
    binary_size: int = 0
    frames: int = 1


@image_bp.route("/images/info", methods=Methods.common())
@api_doc(APIDoc(usage="Upload an image file and show its info like size and type"))
def images_info():
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    img = handler.image

    return success(
        ImageInfo(
            width=img.size[0],
            height=img.size[1],
            mime_type=handler.guess_mime.mime,
            binary_size=handler.raw_size,
            frames=handler.frames,
        )
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
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    if handler.guess_mime != ImageMIME.JPEG:
        err = APIError(message="This endpoint is only for processing JPEG images")
        return error(err)

    # Now we have a valid JPEG.
    # Two things to do:
    #
    # 1. Remove GPS
    # 2. Auto Rotate
    try:
        handler.auto_rotated().remove_exif(ExifTag.GPS_INFO)
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message=f"Failed to prepare image: {e}"), status=500)
    return success(
        {
            "uploaded": {
                "size": handler.raw_size,
                "mime": handler.guess_mime.mime,
            },
            "status": "ok",
            "output": handler.b64_content,
            "success": True,
        }
    )


@image_bp.route("/images/fit/<int:box>", methods=Methods.common())
@api_doc(
    APIDoc(usage="Upload an image file and fit it into a box of the specified size")
)
def fit(box: int):
    # Check uploaded file is valid or not.
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    # Now we have a valid image.
    # Fit it into a box of the specified size.
    _image: Image = handler.image

    start = time.time()
    _resized_content = _rescale_aspect_ratio(_image, box)
    if _resized_content is None:
        return error(APIError(message="Error occurred during rescaling"), status=500)
    resized_content = base64.b64encode(_resized_content).decode("utf-8")
    end = time.time()

    if request.args.get("simple"):
        return success(resized_content, mimetype=handler.guess_mime.mime)

    return success(
        {
            "uploaded": {
                "size": handler.raw_size,
                "mime": handler.guess_mime.mime,
            },
            "status": "ok",
            "success": True,
            "start": start,
            "end": end,
            "cost": int((end - start) * 1000),
            "output": resized_content,
        }
    )


@image_bp.route("/images/resize_avatar", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload an image file in supported format, and resize for website "
        f"avatars in the following sizes: {AvatarSize.supported_desc()}. "
        f"Supported formats are: {', '.join(ImageMIME.all())}"
    )
)
def resize_avatar():
    # TODO resize image that with frames(gif/webp/..)
    # Check uploaded file is valid or not.
    received = get_file_bytes()
    if isinstance(received, APIError):
        return error(received)

    handler = ImageHandle(received)
    if not handler.is_valid:
        return error(APIError(message="Unable to determine the file type"))

    # Now we have a valid image, and we know its size and type.
    # Resize it to each size contained in `AvatarSize`.

    start = time.time()
    try:
        # Confirmation basic avatar to resize.
        # Try to use max size avatar otherwise use original(rotated).
        base_avatar = handler.auto_rotated().image
        if _standard_avatar := _try_rescale(base_avatar, max(AvatarSize)):
            base_avatar = ImageHandle.load_from_bytes(_standard_avatar)

        avatars = {
            f"avatar{size}": avatar_summary
            for size in AvatarSize
            if (avatar_summary := _get_avatar_summary(base_avatar, size))
        }
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message=f"Failed to resize the uploaded image file: {e}"))
    end = time.time()

    return success(
        {
            "uploaded": {
                "size": handler.raw_size,
                "mime": handler.guess_mime.mime,
            },
            "status": "ok",
            "success": True,
            "start": start,
            "end": end,
            "cost": int((end - start) * 1000),
            **avatars,
        }
    )


def get_file_bytes() -> APIError | bytes:
    if not (_uploaded := request.files.get("file")):
        return APIError(message="No file was uploaded")
    return _uploaded.read()


def _get_avatar_summary(base_avatar: Image, size: AvatarSize):
    if avatar_data := _try_rescale(base_avatar, size, force=size.is_mandatory):
        return {
            "size": len(avatar_data),
            "body": base64.b64encode(avatar_data).decode("utf-8"),
        }


def _try_rescale(img: Image, size: AvatarSize, force: bool = False) -> bytes | None:
    _size = size.value
    if not force and not all(i >= _size for i in img.size):
        return
    try:
        with io.BytesIO() as io_obj:
            thumbnail = resizeimage.resize_cover(img, [_size, _size], validate=False)
            thumbnail.save(io_obj, format="PNG")
            return io_obj.getvalue()
    except Exception as e:  # noqa
        capture_exception(e)
        return None


def _rescale_aspect_ratio(image: Image, box: int) -> bytes | None:
    try:
        with io.BytesIO() as io_obj:
            thumbnail = resizeimage.resize_thumbnail(image, [box, box])
            thumbnail.save(io_obj, format=image.format)
            return io_obj.getvalue()
    except Exception as e:  # noqa
        capture_exception(e)
        return
